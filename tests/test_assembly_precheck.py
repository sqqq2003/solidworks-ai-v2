"""Issue #6 module 3: assembly mate / DOF / motion / interference pre-check tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from src.a01_next.assembly_precheck import (
    MockMechanicalCheckPort,
    dof_report,
    interference_check,
    motion_check,
)


class DofReportTests(unittest.TestCase):
    def test_single_revolute_leaves_one_rotation(self):
        report = dof_report(
            components=2,
            mates=[{"type": "revolute", "between": ["frame", "door"]}],
        )
        self.assertEqual(report["backend"], "mock")
        self.assertEqual(report["model"], "simplified_dof_table_not_a_solver")
        self.assertFalse(report["mates_solved"])
        self.assertFalse(report["cad_executed"])
        self.assertEqual(report["sw_live"], "not_applicable_on_linux")
        self.assertEqual(report["dof_before"], 6)
        self.assertEqual(report["dof_removed"], 5)
        self.assertEqual(report["dof"], 1)
        self.assertFalse(report["over_constrained"])

    def test_lock_fixes_the_assembly(self):
        report = dof_report(components=2, mates=[{"type": "lock", "between": ["a", "b"]}])
        self.assertEqual(report["dof"], 0)
        self.assertEqual(report["rows"][0]["dof_removed"], 6)

    def test_redundant_mate_is_flagged_not_negative(self):
        report = dof_report(
            components=2,
            mates=[
                {"type": "lock", "between": ["a", "b"]},
                {"type": "lock", "between": ["a", "b"]},
            ],
        )
        self.assertTrue(report["over_constrained"])
        self.assertEqual(report["dof"], 0)
        self.assertEqual([row["status"] for row in report["rows"]], ["counted", "redundant"])

    def test_unmodeled_mate_type_is_flagged(self):
        report = dof_report(
            components=2,
            mates=[
                {"type": "cam", "between": ["a", "b"]},
                {"type": "revolute", "between": ["a", "b"]},
            ],
        )
        self.assertEqual(report["rows"][0]["status"], "not_modeled")
        self.assertEqual(report["rows"][0]["dof_removed"], 0)
        self.assertEqual(report["dof"], 1)

    def test_unknown_mate_type_is_rejected(self):
        with self.assertRaises(ValueError):
            dof_report(components=2, mates=[{"type": "weld"}])

    def test_invalid_components_rejected(self):
        with self.assertRaises(ValueError):
            dof_report(components=0, mates=[])

    def test_grounded_component_is_reported(self):
        report = dof_report(
            components=3,
            mates=[{"type": "revolute", "between": ["frame", "door"]}],
            grounded_component="frame",
        )
        self.assertEqual(report["grounded_component"], "frame")
        self.assertEqual(report["mobile_components"], 2)
        self.assertEqual(report["dof_before"], 12)


class MotionCheckTests(unittest.TestCase):
    def setUp(self):
        self.report = dof_report(
            components=2, mates=[{"type": "revolute", "between": ["frame", "door"]}]
        )

    def test_motion_parameters_only(self):
        result = motion_check(self.report, sweep_degrees=90.0)
        self.assertEqual(result["status"], "not_checked")
        self.assertFalse(result["motion_verified"])
        self.assertFalse(result["cad_executed"])
        self.assertEqual(result["sw_live"], "not_applicable_on_linux")
        self.assertEqual(result["free_dof"], 1)
        self.assertEqual(result["requested_sweep_degrees"], 90.0)
        self.assertIn("motion study was not run", result["reason"])

    def test_no_free_dof_message(self):
        fixed = dof_report(components=2, mates=[{"type": "lock", "between": ["a", "b"]}])
        result = motion_check(fixed)
        self.assertIn("no free DOF", result["reason"])

    def test_invalid_sweep_rejected(self):
        with self.assertRaises(ValueError):
            motion_check(self.report, sweep_degrees=0.0)
        with self.assertRaises(ValueError):
            motion_check(self.report, sweep_degrees=400.0)


class InterferenceCheckTests(unittest.TestCase):
    def test_overlapping_boxes_are_reported(self):
        report = interference_check(
            [
                {"name": "frame", "bounds": (0, 0, 0, 100, 100, 100)},
                {"name": "roller", "bounds": (50, 50, 50, 150, 150, 150)},
            ]
        )
        self.assertEqual(report["backend"], "mock_aabb")
        self.assertFalse(report["exact_interference"])
        self.assertEqual(report["overlapping"], ["frame", "roller"])
        overlap = report["pairs"][0]
        self.assertEqual(overlap["status"], "overlap")
        self.assertAlmostEqual(overlap["overlap_volume_mm3"], 125000.0)

    def test_clear_and_touching_boxes(self):
        report = interference_check(
            [
                {"name": "a", "bounds": (0, 0, 0, 10, 10, 10)},
                {"name": "b", "bounds": (10, 0, 0, 20, 10, 10)},
                {"name": "c", "bounds": (100, 100, 100, 110, 110, 110)},
            ]
        )
        self.assertEqual(report["overlapping"], [])
        self.assertTrue(all(pair["status"] == "clear" for pair in report["pairs"]))

    def test_invalid_bounds_rejected(self):
        with self.assertRaises(ValueError):
            interference_check(
                [
                    {"name": "a", "bounds": (10, 0, 0, 0, 10, 10)},
                    {"name": "b", "bounds": (0, 0, 0, 10, 10, 10)},
                ]
            )

    def test_single_part_rejected(self):
        with self.assertRaises(ValueError):
            interference_check([{"name": "a", "bounds": (0, 0, 0, 1, 1, 1)}])


class MockMechanicalCheckPortTests(unittest.TestCase):
    def test_port_answers_with_mock_reports(self):
        port = MockMechanicalCheckPort(
            components=2,
            mates=[{"type": "revolute", "between": ["frame", "door"]}],
            parts=[
                {"name": "frame", "bounds": (0, 0, 0, 100, 100, 100)},
                {"name": "door", "bounds": (50, 50, 50, 150, 150, 150)},
            ],
        )
        mates = port.check_mates()
        interference = port.check_interference()
        motion = port.check_motion()
        self.assertTrue(port.simulated)
        self.assertFalse(mates["mates_solved"])
        self.assertFalse(interference["exact_interference"])
        self.assertFalse(motion["motion_verified"])
        for report in (mates, interference, motion):
            self.assertFalse(report["cad_executed"])
            self.assertEqual(report["sw_live"], "not_applicable_on_linux")


if __name__ == "__main__":
    unittest.main()
