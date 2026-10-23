"""QL-5050PX controlled-execution contract; simulated ports never prove CAD."""
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from ql5050px.control import execute_variant, export_native
from ql5050px.parameters import build_plan
from sw_api.transaction_mock import MockExecutionPort


def payload(parameter="frame_length", **overrides):
    row = {
        "parameter": parameter,
        "document": "fixture.SLDASM",
        "configuration": "Default",
        "feature": "Sketch1",
        "dimension": "D1@Sketch1",
        "unit": "mm",
        "depends_on": [],
        "source": "simulation_fixture_only",
        "allowed_range": [0, 5000],
        "component_kind": "editable",
        "status": "confirmed",
    }
    row.update(overrides)
    return {"schema_version": 1, "parameters": [row]}


def plan_with(value=1500.0):
    return build_plan(measurements={
        "frame_length": {"value": value, "source": "simulation_fixture_only", "confirmed": True},
    })


class ContractTests(unittest.TestCase):
    def test_requires_ql_machine_and_mm(self):
        for key, value in (("machine", "GT-ZX"), ("units", "m")):
            plan = plan_with()
            plan[key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    execute_variant(plan, payload(), "copy")

    def test_mapping_payload_is_validated(self):
        plan = plan_with()
        with self.assertRaises(ValueError):
            execute_variant(plan, {"schema_version": 2, "parameters": []}, "copy")
        with self.assertRaises(ValueError):
            execute_variant(plan, payload(parameter="length"), "copy")

    def test_no_writable_mapping_stays_pending(self):
        class Untouchable:
            def __getattr__(self, name):
                raise AssertionError("port must not be touched")

        plan = plan_with()
        result = execute_variant(plan, {"schema_version": 1, "parameters": []}, "copy",
                                 mock_port=Untouchable())
        self.assertEqual(result["status"], "pending_mapping")
        self.assertFalse(result["cad_executed"])
        self.assertEqual(result["pending_mapping"], plan["pending_mapping"])
        self.assertIn("conveyor_width", result["pending_mapping"])
        self.assertNotIn("frame_length", result["pending_mapping"])

    def test_non_editable_or_pending_rows_are_not_written(self):
        for overrides in ({"component_kind": "fixed"}, {"component_kind": "purchased"},
                          {"status": "unconfirmed"}, {"status": "pending_mapping"}):
            with self.subTest(overrides=overrides):
                row = payload(**overrides)
                # Pending rows must satisfy the published mapping validator.
                for entry in row["parameters"]:
                    if entry["status"] != "confirmed":
                        for key in ("document", "configuration", "feature", "dimension", "source"):
                            entry[key] = None
                        entry["allowed_range"] = None
                result = execute_variant(plan_with(), row, "copy")
                self.assertEqual(result["status"], "pending_mapping")
                self.assertFalse(result["cad_executed"])

    def test_unresolved_target_refused(self):
        with self.assertRaisesRegex(ValueError, "unresolved target"):
            execute_variant(build_plan(), payload(parameter="conveyor_width"), "copy")

    def test_non_mm_units_refused_for_v1(self):
        for unit in ("deg", "count", "m"):
            with self.subTest(unit=unit):
                with self.assertRaisesRegex(ValueError, "mm only"):
                    execute_variant(plan_with(), payload(unit=unit), "copy")

    def test_mock_port_must_declare_simulation(self):
        class NotSimulated:
            simulated = False

        with self.assertRaises(ValueError):
            execute_variant(plan_with(), payload(), "copy", mock_port=NotSimulated())


class SimulatedExecutionTests(unittest.TestCase):
    def test_simulated_pass_never_claims_cad(self):
        port = MockExecutionPort({"frame_length": 1000})
        result = execute_variant(plan_with(1500), payload(), "work-copy", mock_port=port)
        self.assertEqual(result["execution_status"], "simulated_pass")
        self.assertEqual(result["status"], "review_required")
        self.assertFalse(result["cad_executed"])
        self.assertFalse(result["cad_release_approved"])
        self.assertEqual(result["mechanical_checks"], {"mates": "unverified", "interference": "unverified", "motion": "unverified"})
        self.assertEqual(port.outputs["work-copy"]["frame_length"], 1500)
        self.assertEqual(result["pending_mapping"], plan_with(1500)["pending_mapping"])
        self.assertIn("conveyor_width", result["pending_mapping"])
        self.assertNotIn("target_length", result["pending_mapping"])

    def test_no_changes_does_not_save(self):
        port = MockExecutionPort({"frame_length": 1500})
        result = execute_variant(plan_with(1500), payload(), "work-copy", mock_port=port)
        self.assertEqual(result["execution_status"], "no_changes")
        self.assertNotIn("work-copy", port.outputs)

    def test_failure_is_reported_and_restored(self):
        for stage in ("write", "rebuild", "save_as", "reopen"):
            with self.subTest(stage=stage):
                port = MockExecutionPort({"frame_length": 1000}, fail_at=stage)
                result = execute_variant(plan_with(1500), payload(), "work-copy", mock_port=port)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["recovery_status"], "restored")
                self.assertEqual(port.values["frame_length"], 1000)
                self.assertFalse(port.outputs)

    def test_out_of_range_target_refused(self):
        data = payload(allowed_range=[0, 1000])
        with self.assertRaisesRegex(ValueError, "outside allowed range"):
            execute_variant(plan_with(1500), data, "work-copy",
                            mock_port=MockExecutionPort({"frame_length": 1000}))


class PlatformRefusalTests(unittest.TestCase):
    def test_native_path_requires_windows_and_driver(self):
        if sys.platform != "win32":
            with self.assertRaisesRegex(RuntimeError, "Windows SolidWorks worker required"):
                execute_variant(plan_with(), payload(), "work-copy")
        else:
            with self.assertRaisesRegex(ValueError, "driver required"):
                execute_variant(plan_with(), payload(), "work-copy")


class FakePort:
    def __init__(self):
        self.events = []

    @contextmanager
    def writer(self):
        self.events.append("writer-enter")
        try:
            yield
        finally:
            self.events.append("writer-exit")

    def guarded(self, method, *args):
        self.events.append(method)
        return {"exported_by": method, "args": args}


class ExportTests(unittest.TestCase):
    def test_export_runs_inside_writer_lease(self):
        port = FakePort()
        result = export_native(port, "owned-model", "new.dxf", "flat_dxf")
        self.assertEqual(result["exported_by"], "export_flat_dxf")
        self.assertEqual(port.events, ["writer-enter", "export_flat_dxf", "writer-exit"])

    def test_export_requires_new_correct_extension(self):
        port = FakePort()
        with self.assertRaisesRegex(ValueError, "unsupported native export kind"):
            export_native(port, "model", "new.dxf", "step")
        with self.assertRaises(ValueError):
            export_native(port, "model", "new.sldprt", "flat_dxf")
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / "existing.dxf"
            existing.write_text("occupied", encoding="ascii")
            with self.assertRaises(ValueError):
                export_native(port, "model", existing, "flat_dxf")
            self.assertEqual(existing.read_text(encoding="ascii"), "occupied")
        self.assertEqual(port.events, [])


if __name__ == "__main__":
    unittest.main()
