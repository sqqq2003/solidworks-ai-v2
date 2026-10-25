"""Mock tests for geometry_ir (Linux, standard library only)."""

import copy
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geometry_ir import (
    IR_VERSION,
    mock_roundtrip,
    to_build_request,
    tree_to_ir,
    validate_ir,
)
from geometry_ir.ir import IRError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load_example(name):
    with open(EXAMPLES / name, encoding="utf-8") as handle:
        return json.load(handle)


def sheetmetal_tree():
    return load_example("sheetmetal_tree.json")


def revolve_tree():
    return load_example("revolve_tree.json")


class TestRoundtrip(unittest.TestCase):
    def test_sheetmetal_roundtrip_ok(self):
        result = mock_roundtrip(sheetmetal_tree())
        self.assertTrue(result["ok"], result)
        names = [c["name"] for c in result["checks"]]
        self.assertIn("bend_ba_matches_mock:bend-1", names)
        self.assertIn("unfold_matches_feature_tree", names)

    def test_revolve_roundtrip_ok(self):
        result = mock_roundtrip(revolve_tree())
        self.assertTrue(result["ok"], result)
        names = [c["name"] for c in result["checks"]]
        self.assertIn("revolve_volume_matches_mock:revolve-1", names)
        self.assertIn("execution_order_respects_dependencies", names)

    def test_roundtrip_fails_cleanly_on_pending_tree(self):
        tree = sheetmetal_tree()
        del tree["features"][1]["params"]["k_factor"]
        result = mock_roundtrip(tree)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "validate_pending")


class TestValidation(unittest.TestCase):
    def test_missing_bend_param_is_pending_not_error(self):
        tree = sheetmetal_tree()
        del tree["features"][1]["params"]["k_factor"]
        report = validate_ir(tree_to_ir(tree))
        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"], [])
        self.assertIn(
            {"node_id": "bend-1", "reason": "missing_param:k_factor"},
            report["pending"],
        )

    def test_unknown_feature_type_refused(self):
        tree = sheetmetal_tree()
        tree["features"][0]["type"] = "sweep"
        with self.assertRaises(IRError):
            tree_to_ir(tree)
        ir = tree_to_ir(sheetmetal_tree())
        ir["features"][0]["type"] = "sweep"
        report = validate_ir(ir)
        self.assertIn("unknown feature type", "; ".join(report["errors"]))

    def test_units_must_be_explicit_mm(self):
        tree = sheetmetal_tree()
        del tree["units"]
        with self.assertRaises(IRError):
            tree_to_ir(tree)
        ir = tree_to_ir(sheetmetal_tree())
        ir["units"] = "inch"
        report = validate_ir(ir)
        self.assertFalse(report["ok"])
        self.assertTrue(any("units" in e for e in report["errors"]))

    def test_cycle_and_dangling_dependency_refused(self):
        tree = sheetmetal_tree()
        tree["features"][1]["depends_on"] = ["bend-2"]
        tree["features"][2]["depends_on"] = ["bend-1"]
        with self.assertRaises(IRError):
            tree_to_ir(tree)
        tree = sheetmetal_tree()
        tree["features"][1]["depends_on"] = ["no-such-node"]
        with self.assertRaises(IRError):
            tree_to_ir(tree)

    def test_derived_section_is_cross_check_only(self):
        ir = tree_to_ir(sheetmetal_tree())
        stripped = copy.deepcopy(ir)
        del stripped["derived"]
        self.assertEqual(
            (validate_ir(ir)["ok"], validate_ir(ir)["errors"],
             validate_ir(ir)["pending"]),
            (validate_ir(stripped)["ok"], validate_ir(stripped)["errors"],
             validate_ir(stripped)["pending"]),
        )
        mutated = copy.deepcopy(ir)
        mutated["derived"]["unfold"]["unfold_length_mm"] = 999999.0
        request_a, _ = to_build_request(
            ir, title="part.SLDPRT", part_path="staging/part.SLDPRT",
            plan_id="plan-1", flip_direction=False)
        request_b, _ = to_build_request(
            mutated, title="part.SLDPRT", part_path="staging/part.SLDPRT",
            plan_id="plan-1", flip_direction=False)
        self.assertEqual(request_a, request_b)


class TestBuildRequest(unittest.TestCase):
    def test_section12_field_alignment(self):
        request, report = to_build_request(
            tree_to_ir(sheetmetal_tree()),
            title="part.SLDPRT", part_path="staging/part.SLDPRT",
            plan_id="plan-1", flip_direction=False)
        self.assertTrue(report["ok"], report)
        self.assertEqual(
            set(request),
            {"plan_id", "title", "part_path", "thickness_mm", "radius_mm",
             "angle_degrees", "k_factor", "flip_direction", "bend_count",
             "idempotency_key", "units"},
        )
        self.assertEqual(request["units"], "mm")
        self.assertEqual(request["bend_count"], 2)
        self.assertEqual(request["thickness_mm"], 2.0)
        self.assertEqual(request["k_factor"], 0.38)
        self.assertEqual(
            request["idempotency_key"],
            hashlib.sha256(b"plan-1:S1:build").hexdigest(),
        )

    def test_non_uniform_bends_withheld(self):
        tree = sheetmetal_tree()
        tree["features"][2]["params"]["k_factor"] = 0.40
        request, report = to_build_request(
            tree_to_ir(tree),
            title="part.SLDPRT", part_path="staging/part.SLDPRT",
            plan_id="plan-1", flip_direction=False)
        self.assertIsNone(request)
        self.assertIn("bend_params_not_uniform", "; ".join(report["pending"]))

    def test_flip_direction_has_no_default(self):
        ir = tree_to_ir(sheetmetal_tree())
        with self.assertRaises(TypeError):
            to_build_request(
                ir, title="part.SLDPRT", part_path="staging/part.SLDPRT",
                plan_id="plan-1")
        with self.assertRaises(ValueError):
            to_build_request(
                ir, title="part.SLDPRT", part_path="staging/part.SLDPRT",
                plan_id="plan-1", flip_direction="false")

    def test_revolve_tree_cannot_use_sheetmetal_build(self):
        request, report = to_build_request(
            tree_to_ir(revolve_tree()),
            title="shaft.SLDPRT", part_path="staging/shaft.SLDPRT",
            plan_id="plan-2", flip_direction=False)
        self.assertIsNone(request)
        self.assertTrue(
            any("non_sheetmetal_feature" in p for p in report["pending"])
        )

    def test_no_defaults_in_module_source(self):
        package = Path(__file__).resolve().parents[1]
        for path in package.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("DEFAULT_", text, path.name)
            self.assertNotRegex(
                text, r"k_factor\s*=\s*0\.\d", path.name)
            self.assertNotIn("0.44", text, path.name)


class TestCli(unittest.TestCase):
    def _run_cli(self, tree, extra_args=()):
        tmp = tempfile.mkdtemp()
        input_path = Path(tmp) / "tree.json"
        input_path.write_text(json.dumps(tree), encoding="utf-8")
        out_dir = Path(tmp) / "out"
        proc = subprocess.run(
            [sys.executable, "-m", "geometry_ir.cli", str(input_path),
             "--out-dir", str(out_dir), *extra_args],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]),
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        )
        return proc, out_dir

    def test_cli_end_to_end_with_build(self):
        proc, out_dir = self._run_cli(sheetmetal_tree(), (
            "--title", "part.SLDPRT", "--part-path", "staging/part.SLDPRT",
            "--plan-id", "plan-1", "--flip-direction", "false"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        request = json.loads((out_dir / "build_request.json").read_text())
        self.assertEqual(request["bend_count"], 2)
        ir = json.loads((out_dir / "geometry_ir.json").read_text())
        self.assertEqual(ir["format"], IR_VERSION)

    def test_cli_pending_tree_exits_1_without_build(self):
        tree = sheetmetal_tree()
        del tree["features"][1]["params"]["k_factor"]
        proc, out_dir = self._run_cli(tree, (
            "--title", "part.SLDPRT", "--part-path", "staging/part.SLDPRT",
            "--plan-id", "plan-1", "--flip-direction", "false"))
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((out_dir / "build_request.json").exists())

    def test_cli_bad_json_exits_2(self):
        tmp = tempfile.mkdtemp()
        bad = Path(tmp) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "geometry_ir.cli", str(bad),
             "--out-dir", str(Path(tmp) / "out")],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
        )
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
