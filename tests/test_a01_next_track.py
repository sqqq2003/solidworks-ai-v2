"""Scaffolds for mate check, sheet metal, and drawing export."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.a01_next.drawing_export import drawing_export_skeleton
from src.a01_next.mate_check import check_mates
from src.a01_next.sheet_metal_hook import SHEET_METAL_ENTRY, sheet_metal_hook
from src.a01_parametric.solver import solve_spec


class NextTrackTests(unittest.TestCase):
    def setUp(self):
        self.plan = solve_spec()

    def test_mate_check_stays_unsolved(self):
        report = check_mates(self.plan)
        self.assertEqual(report["status"], "scaffold")
        self.assertFalse(report["mates_solved"])
        self.assertFalse(report["cad_executed"])
        self.assertEqual(report["sw_live"], "not_applicable_on_linux")
        self.assertEqual(len(report["rows"]), len(self.plan["interface_checks"]))
        self.assertTrue(all(row["mate_status"] == "not_checked" for row in report["rows"]))

    def test_sheet_metal_hook_delegates_without_a_second_generator(self):
        idle = sheet_metal_hook(self.plan)
        self.assertEqual(idle["entry"], SHEET_METAL_ENTRY)
        self.assertFalse(idle["called"])
        self.assertIsNone(idle["thickness_mm"])
        seen = {}

        def executor(function, request):
            seen["name"] = function.__name__
            seen["module"] = function.__module__
            self.assertFalse(request["cad_executed"])
            return "not-executed"

        delegated = sheet_metal_hook(self.plan, executor=executor)
        self.assertTrue(delegated["called"])
        self.assertEqual(delegated["status"], "delegated_to_existing_generator")
        self.assertEqual(seen, {"name": "generate_sheet_metal", "module": "solidworks_generator"})
        self.assertEqual(delegated["result"], "not-executed")

    def test_drawing_skeleton_writes_no_files(self):
        report = drawing_export_skeleton(self.plan)
        self.assertEqual(report["aligned_modules"], ["roller_drawing", "drawing_notes", "roller_spec"])
        self.assertEqual(report["outputs"], [])
        self.assertFalse(report["dxf_written"])
        self.assertFalse(report["dwg_written"])
        self.assertFalse(report["slddrw_written"])
        self.assertEqual(report["envelope_mm"], {"length": 1800.0, "width": 900.0, "height": 1500.0})


if __name__ == "__main__":
    unittest.main()
