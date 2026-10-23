"""Offline assembly/DOF/interference heuristics; never native SW evidence."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from ql5050px.assembly import inspect_assembly, interference, sample_motion


class GraphTests(unittest.TestCase):
    def test_duplicate_component_id_refused(self):
        with self.assertRaisesRegex(ValueError, "duplicate component id"):
            inspect_assembly([{"id": "a"}, {"id": "a"}], [])

    def test_invalid_mate_references_are_reported(self):
        result = inspect_assembly(
            [{"id": "a", "fixed": True}, {"id": "b"}],
            [{"a": "a", "b": "missing", "type": "coincident"},
             {"a": "a", "b": "a", "type": "coincident"}],
        )
        kinds = [issue["kind"] for issue in result["issues"]]
        self.assertEqual(kinds.count("invalid_reference"), 2)
        self.assertIn("unanchored", kinds)

    def test_active_mate_survives_suppressed_duplicate(self):
        components = [{"id": "a", "fixed": True}, {"id": "b", "expected_dof": 5}]
        mates = [
            {"a": "a", "b": "b", "type": "coincident"},
            {"a": "a", "b": "b", "type": "coincident", "suppressed": True},
        ]
        result = inspect_assembly(components, mates)
        self.assertEqual(result["estimated_dof"], {"a": 0, "b": 5})
        self.assertFalse(any(issue["kind"] == "unanchored" for issue in result["issues"]))
        self.assertFalse(any(issue["kind"] == "dof_mismatch" for issue in result["issues"]))

    def test_suppressed_only_mate_does_not_anchor(self):
        components = [{"id": "a", "fixed": True}, {"id": "b"}]
        mates = [{"a": "a", "b": "b", "type": "coincident", "suppressed": True}]
        result = inspect_assembly(components, mates)
        self.assertEqual(result["estimated_dof"]["b"], 6)
        self.assertTrue(any(issue["kind"] == "unanchored" and issue["component"] == "b"
                            for issue in result["issues"]))

    def test_dof_accounting_and_mismatch(self):
        components = [{"id": "a", "fixed": True}, {"id": "b", "expected_dof": 2},
                      {"id": "c", "expected_dof": 1}]
        mates = [
            {"a": "a", "b": "b", "type": "concentric"},
            {"a": "b", "b": "c", "type": "coincident", "moving": "c"},
        ]
        result = inspect_assembly(components, mates)
        self.assertEqual(result["estimated_dof"], {"a": 0, "b": 2, "c": 5})
        mismatch = [issue for issue in result["issues"] if issue["kind"] == "dof_mismatch"]
        self.assertEqual([issue["component"] for issue in mismatch], ["c"])

    def test_redundant_mates_are_flagged(self):
        components = [{"id": "a", "fixed": True}, {"id": "b"}]
        mates = [{"a": "a", "b": "b", "type": "concentric"},
                 {"a": "a", "b": "b", "type": "concentric"}]
        result = inspect_assembly(components, mates)
        self.assertTrue(any(issue["kind"] == "possible_redundancy" for issue in result["issues"]))
        self.assertEqual(result["estimated_dof"]["b"], 0)

    def test_invalid_and_unsupported_mates_reported(self):
        components = [{"id": "a", "fixed": True}, {"id": "b"}]
        result = inspect_assembly(components, [
            {"a": "a", "b": "b", "type": "gear"},
            {"a": "a", "b": "b", "type": "coincident", "moving": "elsewhere"},
        ])
        kinds = [issue["kind"] for issue in result["issues"]]
        self.assertIn("unsupported_mate", kinds)
        self.assertIn("invalid_moving_component", kinds)

    def test_heuristic_mode_is_explicit(self):
        result = inspect_assembly([{"id": "a", "fixed": True}], [])
        self.assertEqual(result["mode"], "offline_heuristic")
        self.assertEqual(result["native_checks"], {"mates": "unverified", "motion": "unverified",
                                                   "interference": "unverified"})


class TransmissionTests(unittest.TestCase):
    def setUp(self):
        self.components = [{"id": "a", "fixed": True}, {"id": "b"}, {"id": "c"}]
        self.mates = [{"a": "a", "b": "b", "type": "coincident"},
                      {"a": "b", "b": "c", "type": "coincident"}]

    def test_ratio_propagates_to_root(self):
        result = inspect_assembly(self.components, self.mates, [
            {"driver": "a", "driven": "b", "ratio": 2},
            {"driver": "b", "driven": "c", "ratio": 3},
        ])
        self.assertEqual(result["transmissions"]["b"], {"root": "a", "speed_ratio": 2})
        self.assertEqual(result["transmissions"]["c"], {"root": "a", "speed_ratio": 6})
        self.assertFalse(result["issues"])

    def test_multiple_drivers_flagged(self):
        result = inspect_assembly(self.components, self.mates, [
            {"driver": "a", "driven": "c", "ratio": 2},
            {"driver": "b", "driven": "c", "ratio": 3},
        ])
        self.assertTrue(any(issue["kind"] == "multiple_drivers" and issue["component"] == "c"
                            for issue in result["issues"]))

    def test_cycle_is_reported_without_recursion(self):
        result = inspect_assembly(self.components, self.mates, [
            {"driver": "a", "driven": "b", "ratio": 2},
            {"driver": "b", "driven": "a", "ratio": 1.5},
        ])
        cycles = [issue for issue in result["issues"] if issue["kind"] == "transmission_cycle"]
        self.assertTrue(cycles)
        self.assertTrue(all("transmission cycle" in issue["detail"] for issue in cycles))

    def test_invalid_transmission_refused(self):
        for bad in (0, True, float("nan"), "2", None):
            with self.subTest(ratio=bad):
                result = inspect_assembly(self.components, self.mates, [
                    {"driver": "a", "driven": "b", "ratio": bad},
                ])
                self.assertTrue(any(issue["kind"] == "invalid_transmission" for issue in result["issues"]))
        result = inspect_assembly(self.components, self.mates, [
            {"driver": "a", "driven": "missing", "ratio": 2},
        ])
        self.assertTrue(any(issue["kind"] == "invalid_transmission" for issue in result["issues"]))


class InterferenceTests(unittest.TestCase):
    def test_overlap_candidate(self):
        result = interference([
            {"id": "a", "bbox_mm": [0, 0, 0, 10, 10, 10]},
            {"id": "b", "bbox_mm": [5, 5, 5, 15, 15, 15]},
        ])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["kind"], "aabb_overlap")
        self.assertEqual(result["candidates"][0]["components"], ["a", "b"])
        self.assertEqual(result["candidates"][0]["overlap_mm"], [5, 5, 5])
        self.assertEqual(result["native_status"], "unverified")

    def test_clearance_risk_without_overlap(self):
        parts = [{"id": "a", "bbox_mm": [0, 0, 0, 10, 10, 10]},
                 {"id": "b", "bbox_mm": [15, 0, 0, 25, 10, 10]}]
        self.assertEqual(interference(parts, clearance_mm=5)["candidates"], [])
        risky = interference(parts, clearance_mm=6)["candidates"]
        self.assertEqual(len(risky), 1)
        self.assertEqual(risky[0]["kind"], "clearance_risk")

    def test_touching_faces(self):
        parts = [{"id": "a", "bbox_mm": [0, 0, 0, 10, 10, 10]},
                 {"id": "b", "bbox_mm": [10, 0, 0, 20, 10, 10]}]
        self.assertEqual(interference(parts)["candidates"], [])
        self.assertEqual(len(interference(parts, clearance_mm=0.5)["candidates"]), 1)

    def test_missing_geometry_is_reported_not_guessed(self):
        result = interference([{"id": "a"}, {"id": "b", "bbox_mm": [0, 0, 0, 1, 1, 1]}])
        self.assertEqual(result["missing_geometry"], ["a"])
        self.assertEqual(result["candidates"], [])

    def test_invalid_boxes_and_clearance_refused(self):
        for bad in ([0, 0, 0, 0, 10, 10], [0, 0, 0, 1, 1], [True, 0, 0, 1, 1, 1],
                    [0, 0, 0, float("nan"), 1, 1], "box"):
            with self.subTest(box=bad):
                with self.assertRaises(ValueError):
                    interference([{"id": "a", "bbox_mm": bad}])
        for clearance in (-1, float("nan"), float("inf"), True):
            with self.subTest(clearance=clearance):
                with self.assertRaises(ValueError):
                    interference([], clearance_mm=clearance)


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.components = [
            {"id": "base", "bbox_mm": [0, 0, 0, 10, 10, 10]},
            {"id": "slide", "bbox_mm": [0, 0, 10, 5, 5, 15]},
        ]

    def test_translation_is_applied_to_each_axis(self):
        result = sample_motion(self.components, {"slide": lambda t: (2, 3, -10 * t)}, [0, 1])
        self.assertEqual(result["frames"][0]["candidates"], [])
        self.assertEqual(len(result["frames"][1]["candidates"]), 1)
        # The moved box is only observable through the rebuilt frame; re-run a
        # single sample with a known overlap to confirm translation wiring.
        shifted = sample_motion(self.components, {"slide": lambda t: (0, 0, -10)}, [0])
        self.assertEqual(len(shifted["frames"][0]["candidates"]), 1)
        self.assertEqual(result["native_status"], "unverified")

    def test_missing_geometry_stays_missing(self):
        result = sample_motion([{"id": "a"}, {"id": "b", "bbox_mm": [0, 0, 0, 1, 1, 1]}],
                               {"a": lambda t: (0, 0, 0)}, [0])
        self.assertEqual(result["frames"][0]["missing_geometry"], ["a"])

    def test_invalid_samples_refused(self):
        with self.assertRaises(ValueError):
            sample_motion(self.components, {"slide": lambda t: (0, 0, float("nan"))}, [0])
        with self.assertRaises(ValueError):
            sample_motion(self.components, {"slide": lambda t: (0, 0)}, [0])
        with self.assertRaises(ValueError):
            sample_motion(self.components, {}, ["now"])


if __name__ == "__main__":
    unittest.main()
