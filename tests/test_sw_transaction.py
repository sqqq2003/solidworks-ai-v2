"""Failure injection checks are simulation contracts, not mechanical acceptance."""
import copy
import sys
import unittest
from dataclasses import asdict

from src.a01_parametric.solver import solve_spec
from src.sw_api.mapping import ParameterMapping, load_mappings, mapping_template
from src.sw_api.transaction import execute
from src.sw_api.transaction_mock import MockExecutionPort
from src.sw_api.windows_execution import WindowsExecutionPort


def payload():
    return {"schema_version": 1, "parameters": [asdict(ParameterMapping(
        parameter="length", document="fixture.SLDASM", configuration="Default",
        feature="Sketch1", dimension="D1@Sketch1", source="simulation_fixture_only",
        allowed_range=(100, 3000), status="confirmed"))]}


class TransactionTests(unittest.TestCase):
    def test_1800_envelope_persist_reopen_idempotency(self):
        plan = solve_spec()
        port = MockExecutionPort({"length": 1000})
        report = execute(plan, payload(), port, "work-copy")
        self.assertEqual(report["execution_status"], "simulated_pass")
        self.assertEqual(port.outputs["work-copy"]["length"], 1800)
        self.assertEqual(report["status"], "review_required")
        self.assertFalse(report["cad_executed"])
        self.assertEqual(set(report["mechanical_checks"].values()), {"unverified"})
        self.assertIsNone(plan["values_mm"]["chain_pitch"])
        second = execute(plan, payload(), port, "another-copy")
        self.assertEqual(second["execution_status"], "no_changes")
        self.assertNotIn("another-copy", port.outputs)

    def test_each_mutation_failure_restores_state_and_output(self):
        for stage in ("write", "rebuild", "save_as", "reopen"):
            with self.subTest(stage=stage):
                port = MockExecutionPort({"length": 1000}, fail_at=stage)
                result = execute(solve_spec(), payload(), port, "copy")
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["recovery_status"], "restored")
                self.assertEqual(port.values, {"length": 1000})
                self.assertFalse(port.outputs)
                self.assertFalse(port.locked)

    def test_bad_readback_after_reopen_restores(self):
        class Corrupt(MockExecutionPort):
            def reopen(self, destination):
                super().reopen(destination)
                self.values["length"] = 17
        port = Corrupt({"length": 1000})
        result = execute(solve_spec(), payload(), port, "copy")
        self.assertEqual(result["recovery_status"], "restored")
        self.assertFalse(port.outputs)

    def test_rebuild_readback_and_stale_plan_fail_closed(self):
        class Corrupt(MockExecutionPort):
            def rebuild(self):
                super().rebuild()
                self.values["length"] = 42
        class Stale(MockExecutionPort):
            def checkpoint(self):
                saved = super().checkpoint()
                self.values["length"] = 77
                return saved
        for cls in (Corrupt, Stale):
            port = cls({"length": 1000})
            result = execute(solve_spec(), payload(), port, "copy")
            self.assertEqual(result["recovery_status"], "restored")
            self.assertEqual(port.values["length"], 1000)
            self.assertFalse(port.outputs)

    def test_invalid_units_and_numbers_refused(self):
        for unit in ("deg", "count"):
            data = payload()
            data["parameters"][0]["unit"] = unit
            with self.assertRaises(ValueError):
                execute(solve_spec(), data, MockExecutionPort({"length": 1000}), "copy")
        for bad in (float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                execute(solve_spec(), payload(), MockExecutionPort({"length": bad}), "copy")

    def test_recovery_failure_is_explicit(self):
        class Broken(MockExecutionPort):
            def restore(self, checkpoint):
                raise RuntimeError("recovery unavailable")
        result = execute(solve_spec(), payload(), Broken({"length": 1000}, "rebuild"), "copy")
        self.assertEqual(result["recovery_status"], "recovery_required")

    def test_range_or_missing_target_never_writes(self):
        for values, limit in (({}, 3000), ({"length": 1000}, 1500)):
            with self.subTest(values=values):
                data = payload()
                data["parameters"][0]["allowed_range"] = [100, limit]
                port = MockExecutionPort(values)
                with self.assertRaises(ValueError):
                    execute(solve_spec(), data, port, "copy")
                self.assertNotIn("write", port.calls)

    def test_unknown_protected_and_pending_mappings(self):
        plan = solve_spec()
        for kind, status in (("fixed", "confirmed"), ("purchased", "confirmed"), ("editable", "pending_mapping")):
            data = payload()
            data["parameters"][0].update(component_kind=kind, status=status)
            port = MockExecutionPort({"length": 1000})
            result = execute(plan, data, port, "copy")
            self.assertIn("length", result["pending_mapping"])
            self.assertNotIn("write", port.calls)
        data = payload()
        data["parameters"][0]["parameter"] = "invented"
        with self.assertRaises(ValueError):
            execute(plan, data, MockExecutionPort({}), "copy")

    def test_schema_rejects_duplicates_and_incomplete_confirmation(self):
        data = payload()
        data["parameters"].append(copy.deepcopy(data["parameters"][0]))
        with self.assertRaises(ValueError):
            load_mappings(data)
        data = payload()
        data["parameters"][0]["source"] = None
        with self.assertRaises(ValueError):
            load_mappings(data)
        self.assertTrue(all(row.status == "pending_mapping" for row in load_mappings(mapping_template(solve_spec()))))

    def test_single_writer_and_existing_output(self):
        port = MockExecutionPort({"length": 1000})
        with port.writer():
            with self.assertRaises(RuntimeError):
                execute(solve_spec(), payload(), port, "copy")
        port.outputs["copy"] = {"length": 900}
        with self.assertRaises(ValueError):
            execute(solve_spec(), payload(), port, "copy")
        self.assertEqual(port.outputs["copy"], {"length": 900})

    @unittest.skipIf(sys.platform == "win32", "Linux refusal test")
    def test_windows_bridge_refuses_linux(self):
        with self.assertRaisesRegex(RuntimeError, "not_applicable_on_linux"):
            execute(solve_spec(), payload(), WindowsExecutionPort(None), "copy")
