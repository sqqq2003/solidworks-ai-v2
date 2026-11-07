"""Mock tests for feature_tree (module 4). Pure standard library.

Run from the repository root:
  python -m unittest discover -s feature_tree/tests -t .
"""

import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from feature_tree import (  # noqa: E402
    CycleError,
    DuplicateIdError,
    Executor,
    MissingDependencyError,
    MockSwApp,
    UnknownTypeError,
    build_mock_artifact,
    convert_plan,
    parse_tree,
)
from feature_tree.cli import run as cli_run  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _tree(features, name="t"):
    return parse_tree(
        {"tree_version": "feature-tree/1", "name": name, "units": "mm",
         "features": features}
    )


def _sketch(fid="s1", points=None, deps=None):
    return {
        "id": fid, "type": "sketch",
        "params": {"points": points or [[0, 0], [10, 0], [10, 10], [0, 10]]},
        "depends_on": deps or [],
    }


def _bend(fid="b1", deps=None, **over):
    params = {
        "line": {"start": [5, 0], "end": [5, 10]},
        "thickness_mm": 2.0, "radius_mm": 1.5,
        "angle_degrees": 90.0, "k_factor": 0.38,
    }
    params.update(over)
    return {"id": fid, "type": "bend", "params": params,
            "depends_on": deps or ["s1"]}


class TestOrderingAndRefusal(unittest.TestCase):
    def test_topo_order_respects_dependencies(self):
        tree = _tree([
            _bend(deps=["s1"]),
            _sketch(),
            {"id": "g1", "type": "sheetmetal",
             "params": {"outline_ref": "s1", "bend_refs": ["b1"]},
             "depends_on": ["s1", "b1"]},
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "ok")
        self.assertEqual(record.executed, ["s1", "b1", "g1"])

    def test_cycle_refused(self):
        with self.assertRaises(CycleError):
            _tree([
                _sketch(deps=["b1"]),
                _bend(deps=["s1"]),
            ])

    def test_missing_dependency_refused(self):
        with self.assertRaises(MissingDependencyError):
            _tree([_bend(deps=["nope"])])

    def test_duplicate_id_refused(self):
        with self.assertRaises(DuplicateIdError):
            _tree([_sketch(), _sketch()])

    def test_unknown_type_refused(self):
        with self.assertRaises(UnknownTypeError):
            _tree([{"id": "x", "type": "revolve", "params": {}}])

    def test_units_must_be_explicit_mm(self):
        with self.assertRaises(Exception):
            parse_tree({"tree_version": "feature-tree/1", "units": "inch",
                        "features": [_sketch()]})


class TestExecutionSemantics(unittest.TestCase):
    def test_missing_bend_param_is_pending_and_stops(self):
        tree = _tree([
            _sketch(),
            {"id": "b1", "type": "bend",
             "params": {"line": {"start": [5, 0], "end": [5, 10]},
                        "radius_mm": 1.5, "angle_degrees": 90.0,
                        "k_factor": 0.38},
             "depends_on": ["s1"]},
            {"id": "g1", "type": "sheetmetal",
             "params": {"outline_ref": "s1", "bend_refs": ["b1"]},
             "depends_on": ["s1", "b1"]},
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.failed_node, "b1")
        self.assertEqual(record.failure_kind, "pending_confirmation")
        self.assertEqual(record.executed, ["s1"])
        # Fail-stop: the group node after the failed bend has no record.
        self.assertNotIn("g1", record.executed)
        artifact = build_mock_artifact(record, MockSwApp())
        self.assertNotIn("g1", artifact["executed"])

    def test_mock_record_complete_and_readback_matches_formula(self):
        tree = _tree([_sketch(), _bend()])
        backend = MockSwApp()
        record = Executor(backend).run(tree)
        self.assertEqual(record.status, "ok")
        bend_step = record.steps[1]
        self.assertEqual(bend_step["op"], "make_bend")
        theta = math.radians(90.0)
        expected_ba = theta * (1.5 + 0.38 * 2.0)
        expected_bd = 2.0 * (1.5 + 2.0) * math.tan(theta / 2.0) - expected_ba
        self.assertAlmostEqual(
            bend_step["readback"]["bend_allowance_mm"], expected_ba)
        self.assertAlmostEqual(
            bend_step["readback"]["bend_deduction_mm"], expected_bd)
        self.assertTrue(bend_step["readback"]["mock_readback"])
        artifact = build_mock_artifact(record, backend)
        self.assertEqual(artifact["executed"], ["s1", "b1"])
        self.assertEqual(len(artifact["op_log"]), 2)

    def test_fillet_placeholder_is_pending_not_guessed(self):
        tree = _tree([
            _sketch(),
            {"id": "f1", "type": "fillet",
             "params": {"radius_mm": 2.0}, "depends_on": ["s1"]},
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.failed_node, "f1")
        self.assertIn("unsupported_in_mock:fillet",
                      record.failure_detail)

    def test_no_defaults_in_module_sources(self):
        module_dir = Path(__file__).resolve().parents[1]
        offenders = []
        for path in sorted(module_dir.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for pattern in (r"\bDEFAULT_K\b", r"\bDEFAULT_T\b",
                            r"\bMATERIAL_K_FACTORS\b",
                            r"\bDEFAULT_BEND_K_FACTOR\b"):
                if re.search(pattern, text):
                    offenders.append("%s matches %s" % (path.name, pattern))
        self.assertEqual(offenders, [])


class TestPlanConversion(unittest.TestCase):
    def _plan(self):
        return json.loads((EXAMPLES / "plan_sample.json").read_text())

    def test_all_five_plan_types_convert(self):
        job = json.loads((EXAMPLES / "job_sample.json").read_text())
        tree = convert_plan(self._plan(), job)
        by_id = {node.id: node for node in tree.features}
        self.assertEqual(by_id["f-001"].type, "sketch")
        self.assertEqual(by_id["f-002"].type, "hole")
        self.assertEqual(by_id["f-004"].type, "bend")
        self.assertEqual(by_id["f-005"].type, "sheetmetal")
        self.assertEqual(by_id["f-006"].type, "check")
        # Stale plan-time job reasons are cleared once job params arrive.
        self.assertEqual(by_id["f-004"].status, "confirmed")
        self.assertEqual(by_id["f-005"].status, "confirmed")
        self.assertEqual(by_id["f-005"].depends_on, ["f-001", "f-004"])
        # Dimension check follows the hole derived from its circle.
        self.assertEqual(by_id["f-006"].depends_on, ["f-002"])

    def test_conversion_without_job_params_keeps_bends_pending(self):
        tree = convert_plan(self._plan(), None)
        by_id = {node.id: node for node in tree.features}
        self.assertEqual(by_id["f-004"].status, "pending_confirmation")
        self.assertTrue(any("thickness_mm" in r
                            for r in by_id["f-004"].pending_reasons))
        self.assertEqual(by_id["f-002"].status, "pending_confirmation")

    def test_cli_end_to_end_on_plan_sample(self):
        job = EXAMPLES / "job_sample.json"
        with tempfile.TemporaryDirectory() as tmp:
            code = cli_run(str(EXAMPLES / "plan_sample.json"),
                           str(Path(tmp) / "out"),
                           str(job))
            self.assertEqual(code, 0)
            execution = json.loads(
                (Path(tmp) / "out" / "execution.json").read_text())
            artifact = json.loads(
                (Path(tmp) / "out" / "mock_part.json").read_text())
            self.assertEqual(execution["status"], "ok")
            # Topological order is input-order stable: the check node
            # (depends on f-002) is freed before the sheetmetal group
            # (depends on f-001 + f-004).
            self.assertEqual(execution["executed"],
                             ["f-001", "f-002", "f-003", "f-004",
                              "f-006", "f-005"])
            self.assertTrue(artifact["mock_part"])
            self.assertEqual(len(artifact["op_log"]), 6)

    def test_cli_end_to_end_on_tree_examples(self):
        for name in ("plate_holes_tree.json",
                     "sheetmetal_two_bends_tree.json"):
            with tempfile.TemporaryDirectory() as tmp:
                code = cli_run(str(EXAMPLES / name),
                               str(Path(tmp) / "out"))
                self.assertEqual(code, 0, name)
                execution = json.loads(
                    (Path(tmp) / "out" / "execution.json").read_text())
                self.assertEqual(execution["status"], "ok", name)


if __name__ == "__main__":
    unittest.main()
