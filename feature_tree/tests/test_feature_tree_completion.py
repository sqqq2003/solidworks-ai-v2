"""Mock tests for the feature-tree completion batch (after #36).

Covers revolve, the L-bracket example and whole-part unfold length.
Pure standard library. Run from the repository root:
  python -m unittest discover -s feature_tree/tests -t .
"""

import json
import math
import re
import tempfile
import unittest
from pathlib import Path

sys_path = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(sys_path))

from feature_tree import (  # noqa: E402
    Executor,
    MockSwApp,
    build_mock_artifact,
    compute_unfold,
    parse_tree,
)
from feature_tree.cli import run as cli_run  # noqa: E402
from feature_tree.unfold import run as unfold_run  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MODULE_DIR = Path(__file__).resolve().parents[1]


def _tree(features, name="t"):
    return parse_tree(
        {"tree_version": "feature-tree/1", "name": name, "units": "mm",
         "features": features}
    )


def _sketch(fid="s1", points=None, **extra):
    params = {"points": points or [[0, 0], [10, 0], [10, 10], [0, 10]]}
    params.update(extra)
    return {"id": fid, "type": "sketch", "params": params,
            "depends_on": []}


def _revolve(fid="r1", profile="s1", angle=360.0, axis=None, deps=None):
    params = {
        "profile_sketch": profile,
        "axis": axis or {"origin": [0, 0], "direction": [0, 1]},
        "angle_degrees": angle,
    }
    return {"id": fid, "type": "revolve", "params": params,
            "depends_on": deps if deps is not None else ["s1"]}


def _bend(fid="b1", deps=None, **over):
    params = {
        "line": {"start": [5, 0], "end": [5, 10]},
        "thickness_mm": 2.0, "radius_mm": 1.5,
        "angle_degrees": 90.0, "k_factor": 0.38,
    }
    params.update(over)
    return {"id": fid, "type": "bend", "params": params,
            "depends_on": deps or ["s1"]}


class TestRevolve(unittest.TestCase):
    def test_full_turn_volume_uses_pappus(self):
        # Rectangle 20 (x 20..40) by 20 (y 0..20) around the y axis:
        # area 400, centroid (30, 10), distance 30.
        tree = _tree([
            _sketch(points=[[20, 0], [40, 0], [40, 20], [20, 20]]),
            _revolve(),
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "ok")
        step = record.steps[1]
        self.assertEqual(step["op"], "revolve")
        self.assertTrue(step["readback"]["mock_readback"])
        self.assertAlmostEqual(
            step["readback"]["volume_mm3"], 400 * 2 * math.pi * 30)
        self.assertAlmostEqual(
            step["readback"]["profile_area_mm2"], 400.0)
        self.assertAlmostEqual(
            step["readback"]["centroid_distance_mm"], 30.0)

    def test_partial_angle_scales_volume(self):
        tree = _tree([
            _sketch(points=[[20, 0], [40, 0], [40, 20], [20, 20]]),
            _revolve(angle=180.0),
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "ok")
        self.assertAlmostEqual(
            record.steps[1]["readback"]["volume_mm3"],
            400 * math.pi * 30)

    def test_open_profile_is_pending_not_guessed(self):
        tree = _tree([
            _sketch(closed=False),
            _revolve(),
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.failed_node, "r1")
        self.assertEqual(record.failure_kind, "pending_confirmation")
        self.assertIn("revolve_profile_not_closed",
                      record.failure_detail)

    def test_degenerate_profile_is_pending(self):
        # Collinear points: zero area, no solid can revolve from it.
        tree = _tree([
            _sketch(points=[[0, 0], [10, 0], [20, 0]]),
            _revolve(axis={"origin": [0, 0], "direction": [0, 1]}),
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.failed_node, "r1")
        self.assertIn("revolve_profile_degenerate",
                      record.failure_detail)

    def test_axis_crossing_is_pending_not_repaired(self):
        # Points on both sides of the y axis: the profile crosses it.
        tree = _tree([
            _sketch(points=[[-10, 0], [10, 0], [10, 10], [-10, 10]]),
            _revolve(),
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.failed_node, "r1")
        self.assertIn("revolve_profile_crosses_axis",
                      record.failure_detail)

    def test_profile_on_axis_edge_is_allowed(self):
        # Points on the axis itself are fine; only strict both-side
        # crossings are refused.
        tree = _tree([
            _sketch(points=[[0, 0], [10, 0], [10, 10], [0, 10]]),
            _revolve(),
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "ok")

    def test_missing_angle_is_pending(self):
        node = _revolve()
        del node["params"]["angle_degrees"]
        tree = _tree([_sketch(), node])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.failure_kind, "pending_confirmation")
        self.assertIn("angle_degrees", record.failure_detail)

    def test_angle_out_of_range_is_failed(self):
        tree = _tree([_sketch(), _revolve(angle=400.0)])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.failure_kind, "failed")
        self.assertEqual(record.failed_node, "r1")

    def test_unwired_profile_is_pending(self):
        # Revolve listed before its sketch with no dependency edge:
        # the profile has not executed yet, so revolve must wait
        # instead of reading a sketch that is not there.
        tree = _tree([
            _revolve(deps=[]),
            _sketch(),
        ])
        record = Executor(MockSwApp()).run(tree)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.failed_node, "r1")
        self.assertIn("profile_sketch_not_executed",
                      record.failure_detail)


class TestLBracketExample(unittest.TestCase):
    def test_l_bracket_example_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = cli_run(str(EXAMPLES / "l_bracket_tree.json"),
                           str(Path(tmp) / "out"))
            self.assertEqual(code, 0)
            execution = json.loads(
                (Path(tmp) / "out" / "execution.json").read_text())
            artifact = json.loads(
                (Path(tmp) / "out" / "mock_part.json").read_text())
            self.assertEqual(execution["status"], "ok")
            self.assertEqual(execution["executed"],
                             ["sketch-1", "extrude-1", "hole-1", "hole-2"])
            self.assertTrue(artifact["mock_part"])
            self.assertEqual(len(artifact["op_log"]), 4)


class TestUnfold(unittest.TestCase):
    def _unfold_tree(self):
        return json.loads(
            (EXAMPLES / "sheetmetal_unfold_tree.json").read_text())

    def test_two_bend_math(self):
        tree = parse_tree(self._unfold_tree())
        report = compute_unfold(tree)
        self.assertEqual(report["status"], "ok")
        theta = math.radians(90.0)
        expected_ba = theta * (1.5 + 0.38 * 2.0)
        self.assertAlmostEqual(report["straight_total_mm"], 100.0)
        self.assertAlmostEqual(report["total_bend_allowance_mm"],
                               2 * expected_ba)
        self.assertAlmostEqual(report["unfold_length_mm"],
                               100.0 + 2 * expected_ba)
        self.assertEqual(len(report["bends"]), 2)

    def test_missing_k_factor_is_pending(self):
        doc = self._unfold_tree()
        for feature in doc["features"]:
            if feature["id"] == "bend-1":
                del feature["params"]["k_factor"]
        report = compute_unfold(parse_tree(doc))
        self.assertEqual(report["status"], "pending")
        self.assertIsNone(report["unfold_length_mm"])
        self.assertIsNone(report["total_bend_allowance_mm"])
        bend_entry = [b for b in report["bends"]
                      if b["bend_id"] == "bend-1"][0]
        self.assertIsNone(bend_entry["bend_allowance_mm"])
        self.assertTrue(any("k_factor" in r
                            for r in bend_entry["pending_reasons"]))
        # The computed bend is still reported; nothing is skipped.
        self.assertIsNotNone(
            [b for b in report["bends"]
             if b["bend_id"] == "bend-2"][0]["bend_allowance_mm"])

    def test_non_sheetmetal_features_are_excluded(self):
        tree = _tree([
            _sketch(),
            _bend(),
            {"id": "h1", "type": "hole",
             "params": {"center": [5, 5], "diameter_mm": 4.0,
                        "depth": {"mode": "through_all"}},
             "depends_on": ["s1"]},
            _revolve(),
            {"id": "g1", "type": "sheetmetal",
             "params": {"outline_ref": "s1", "bend_refs": ["b1"],
                        "straight_lengths_mm": [50.0]},
             "depends_on": ["s1", "b1"]},
        ])
        report = compute_unfold(tree)
        self.assertEqual(report["status"], "ok")
        excluded = {e["node_id"]: e["note"] for e in report["excluded"]}
        self.assertEqual(excluded["h1"], "non_sheetmetal_feature")
        self.assertEqual(excluded["r1"], "non_sheetmetal_feature")
        self.assertEqual(excluded["s1"], "outline_reference")
        theta = math.radians(90.0)
        expected_ba = theta * (1.5 + 0.38 * 2.0)
        self.assertAlmostEqual(report["unfold_length_mm"],
                               50.0 + expected_ba)

    def test_unfold_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            code = unfold_run(
                str(EXAMPLES / "sheetmetal_unfold_tree.json"), out)
            self.assertEqual(code, 0)
            report = json.loads(
                (Path(tmp) / "out" / "unfold.json").read_text())
            self.assertEqual(report["status"], "ok")
            self.assertAlmostEqual(report["unfold_length_mm"],
                                   100.0 + 2 * math.radians(90.0)
                                   * (1.5 + 0.38 * 2.0))

    def test_unfold_cli_pending_exit_code(self):
        doc = self._unfold_tree()
        for feature in doc["features"]:
            if feature["id"] == "bend-2":
                del feature["params"]["thickness_mm"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tree.json"
            path.write_text(json.dumps(doc))
            code = unfold_run(str(path), str(Path(tmp) / "out"))
            self.assertEqual(code, 1)
            report = json.loads(
                (Path(tmp) / "out" / "unfold.json").read_text())
            self.assertEqual(report["status"], "pending")


class TestCompletionHygiene(unittest.TestCase):
    def test_no_defaults_in_completion_sources(self):
        # Production sources only: test files may quote the patterns
        # as string literals, so they are not scanned here.
        offenders = []
        for path in sorted(MODULE_DIR.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for pattern in (r"\bDEFAULT_K\b", r"\bDEFAULT_T\b",
                            r"\bMATERIAL_K_FACTORS\b",
                            r"\bDEFAULT_BEND_K_FACTOR\b"):
                if re.search(pattern, text):
                    offenders.append("%s matches %s"
                                     % (path.name, pattern))
        self.assertEqual(offenders, [])

    def test_old_trees_execute_unchanged(self):
        # Backward compatibility: trees written before this batch
        # produce the same steps and the same artifact shape (no new
        # keys), and sketch readback still reports closed=True.
        for name, expected in (
            ("plate_holes_tree.json",
             ["sketch-1", "extrude-1", "hole-1", "hole-2", "hole-3",
              "hole-4"]),
            ("sheetmetal_two_bends_tree.json",
             ["sketch-1", "bend-1", "bend-2", "sheetmetal-1"]),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                code = cli_run(str(EXAMPLES / name),
                               str(Path(tmp) / "out"))
                self.assertEqual(code, 0, name)
                execution = json.loads(
                    (Path(tmp) / "out" / "execution.json").read_text())
                artifact = json.loads(
                    (Path(tmp) / "out" / "mock_part.json").read_text())
                self.assertEqual(execution["executed"], expected, name)
                self.assertEqual(len(artifact["op_log"]),
                                 len(expected), name)
                self.assertNotIn("revolves", artifact, name)
                self.assertTrue(
                    execution["steps"][0]["result"]["closed"], name)


if __name__ == "__main__":
    unittest.main()
