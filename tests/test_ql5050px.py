"""Issue #6 module 1: independent QL-5050PX parameter configuration tests."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from src.ql5050px import cli
from src.ql5050px.config import load_spec, with_envelope
from src.ql5050px.graph import assert_documented
from src.ql5050px.solver import solve, solve_spec


class Ql5050pxConfigTests(unittest.TestCase):
    def test_default_spec_is_independent_and_placeholder_only(self):
        spec = load_spec()
        self.assertEqual(spec["machine_id"], "QL-5050PX")
        self.assertIs(spec["target_envelope_is_placeholder"], True)
        self.assertIsNone(spec["native_template"])
        self.assertIs(spec["engineering_approved"], False)
        self.assertIs(spec["template_identity_confirmed"], False)
        self.assertIn("GT-ZX", spec["no_confirmed_dimensions_copied_from"])

    def test_with_envelope_moves_placeholder_only(self):
        spec = with_envelope(load_spec(), length=2000, width=1000, height=1600)
        self.assertEqual(spec["target_envelope_mm"], {"length": 2000.0, "width": 1000.0, "height": 1600.0})
        self.assertIs(spec["target_envelope_is_placeholder"], True)

    def test_with_envelope_rejects_non_positive(self):
        with self.assertRaises(ValueError):
            with_envelope(load_spec(), length=0)

    def test_placeholder_flag_cannot_be_dropped(self):
        spec = copy.deepcopy(load_spec())
        spec["target_envelope_is_placeholder"] = False
        with self.assertRaises(ValueError):
            with_envelope(spec, length=2000)


class Ql5050pxGraphTests(unittest.TestCase):
    def test_documented_edges_match_spec(self):
        assert_documented(load_spec())

    def test_edge_drift_is_rejected(self):
        spec = copy.deepcopy(load_spec())
        spec["parametric_graph"]["carton_passage_length"]["depends_on"] = ["frame_width"]
        with self.assertRaises(ValueError):
            assert_documented(spec)

    def test_unknown_node_is_rejected(self):
        spec = copy.deepcopy(load_spec())
        spec["parametric_graph"]["ghost"] = {
            "subsystem": "drive",
            "kind": "pending_mapping",
            "unit": "mm",
            "depends_on": ["frame_length"],
        }
        with self.assertRaises(ValueError):
            assert_documented(spec)


class Ql5050pxSolverTests(unittest.TestCase):
    def setUp(self):
        self.plan = solve_spec()

    def test_plan_stays_review_required_and_offline(self):
        self.assertEqual(self.plan["machine_id"], "QL-5050PX")
        self.assertEqual(self.plan["status"], "review_required")
        self.assertEqual(self.plan["sw_live"], "not_applicable_on_linux")
        self.assertFalse(self.plan["cad_executed"])
        self.assertFalse(self.plan["cad_release_approved"])
        self.assertTrue(self.plan["simulated_only"])
        self.assertIs(self.plan["target_envelope_is_placeholder"], True)

    def test_all_oem_dimensions_stay_pending(self):
        pending_ids = [row["mapping_id"] for row in self.plan["pending_mapping"]]
        self.assertEqual(len(pending_ids), 12)
        self.assertIn("QL5050PX.conveyor.passline_height", pending_ids)
        self.assertIn("QL5050PX.carton.passage_height", pending_ids)
        self.assertIn("QL5050PX.interfaces.thread_major_diameter", pending_ids)
        for row in self.plan["pending_mapping"]:
            self.assertTrue(row["mapping_id"].startswith("QL5050PX."))
        for name, value in self.plan["values_mm"].items():
            if name in {"length", "width", "height"}:
                continue
            self.assertIsNone(value, f"{name} must not carry an invented value")

    def test_unresolved_reasons_are_relabeled_for_ql5050px(self):
        reasons = {row["parameter"]: row["reason"] for row in self.plan["unresolved"]}
        self.assertIn("QL-5050PX", reasons["engineering_approval"])
        self.assertIn("QL-5050PX", reasons["template_identity"])
        self.assertIn("QL-5050PX", reasons["native_template"])
        for row in self.plan["unresolved"]:
            self.assertNotIn("A01", row["reason"])

    def test_preserved_interfaces_are_never_overwritten(self):
        actions = {row["action"] for row in self.plan["interface_checks"]}
        self.assertEqual(actions, {"preserve_unresolved"})
        rules = {row["rule"] for row in self.plan["interface_checks"]}
        self.assertEqual(rules, set(self.plan["preserve_interfaces"]))

    def test_copy_edges_resolve_when_frame_resolves(self):
        spec = copy.deepcopy(load_spec())
        for name, value in (
            ("front_allowance", 10.0),
            ("rear_allowance", 10.0),
            ("left_allowance", 8.0),
            ("right_allowance", 8.0),
            ("top_allowance", 6.0),
            ("bottom_allowance", 6.0),
        ):
            node = spec["parameter_graph"][name]
            node["value_mm"] = value
            node["confirmed"] = True
            node["source"] = "synthetic test value; not a drawing measurement"
        spec["engineering_approved"] = True
        spec["template_identity_confirmed"] = True
        spec["native_template"] = {"identity": "synthetic-test-template"}
        plan = solve(spec)
        self.assertEqual(plan["values_mm"]["frame_length"], 1780.0)
        self.assertEqual(plan["values_mm"]["frame_width"], 884.0)
        self.assertEqual(plan["values_mm"]["column_height"], 1488.0)
        self.assertEqual(plan["values_mm"]["conveyor_bed_length"], 1780.0)
        self.assertEqual(plan["values_mm"]["conveyor_clear_width"], 884.0)
        # Pending mappings still block a passed plan.
        self.assertEqual(plan["status"], "review_required")
        self.assertIsNone(plan["values_mm"]["passline_height"])

    def test_unconfirmed_measured_override_is_ignored(self):
        # An unconfirmed value never enters the plan, even when the JSON
        # carries one; the parameter stays unresolved instead.
        spec = copy.deepcopy(load_spec())
        node = spec["parameter_graph"]["front_allowance"]
        node["value_mm"] = 10.0
        node["confirmed"] = False
        plan = solve(spec)
        self.assertIsNone(plan["values_mm"]["front_allowance"])
        reasons = {row["parameter"] for row in plan["unresolved"]}
        self.assertIn("front_allowance", reasons)

    def test_cli_returns_review_required_exit_code(self):
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()) as out:
            code = cli.main([])
        self.assertEqual(code, 3)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["machine_id"], "QL-5050PX")
        self.assertEqual(payload["status"], "review_required")

    def test_cli_writes_out_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "nested" / "plan.json"
            with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
                code = cli.main(["--out", str(target)])
            self.assertEqual(code, 3)
            written = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(written["task_id"], "GORK-QL5050PX-001")


if __name__ == "__main__":
    unittest.main()
