"""Estimate module tests: math is plain, assumptions are declared, nothing quoted."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.sheetmetal_estimate import (  # noqa: E402
    EstimateError,
    estimate_job,
    estimate_labor,
    estimate_material,
    plan_geometry,
)
from src.sheetmetal_unfold import unfold_chain, unfold_plan  # noqa: E402


class EstimateTests(unittest.TestCase):
    def test_plan_geometry_accepts_single_plan_shape(self):
        plan = unfold_plan(
            thickness_mm=2.5, radius_mm=1.5, angle_degrees=90.0, k_factor=0.33, legs_mm=[30.0, 40.0]
        )
        geometry = plan_geometry(plan)
        self.assertAlmostEqual(geometry["flat_length_mm"], plan["bend"]["flat_length_mm"], places=9)
        self.assertEqual(geometry["thickness_mm"], 2.5)
        self.assertEqual(geometry["bends"], 1)

    def test_plan_geometry_accepts_chain_shape(self):
        chain = unfold_chain(
            thickness_mm=2.5, radius_mm=1.5, angle_degrees=90.0, k_factor=0.33, segments_mm=[30.0, 40.0, 50.0]
        )
        geometry = plan_geometry(chain, thickness_mm=2.5)
        self.assertAlmostEqual(geometry["flat_length_mm"], chain["flat_length_mm"], places=9)
        self.assertEqual(geometry["bends"], 2)

    def test_material_estimate_matches_hand_computation(self):
        row = estimate_material(1000.0, 500.0, 2.5, "SUS304")
        self.assertEqual(row["status"], "resolved")
        volume = 1000.0 * 500.0 * 2.5  # mm^3
        expected_kg = volume / 1000.0 * 7.93 * 0.001
        self.assertAlmostEqual(row["mass_kg_per_piece"], expected_kg, places=9)

    def test_material_estimate_unresolved_without_density(self):
        row = estimate_material(1000.0, 500.0, 2.5, "unobtanium")
        self.assertEqual(row["status"], "unresolved")
        self.assertNotIn("mass_kg_per_piece", row)

    def test_labor_scales_with_bends_and_quantity(self):
        labor = estimate_labor(2, 10)
        self.assertAlmostEqual(
            labor["total_minutes"], labor["minutes_per_piece"] * 10, places=9
        )
        self.assertTrue(labor["assumptions"])
        self.assertFalse(any(a["confirmed"] for a in labor["assumptions"]))

    def test_job_report_is_estimate_only_and_declares_assumptions(self):
        chain = unfold_chain(
            thickness_mm=2.5, radius_mm=1.5, angle_degrees=90.0, k_factor=0.33, segments_mm=[30.0, 40.0, 50.0]
        )
        report = estimate_job(chain, width_mm=400.0, material="SUS304", quantity=5, thickness_mm=2.5)
        self.assertTrue(report["estimate_only"])
        self.assertTrue(all(a["confirmed"] is False for a in report["labor"]["assumptions"]))
        self.assertFalse(report["waste_factor"]["confirmed"])
        self.assertEqual(report["sw_live"], "not_applicable_on_linux")
        self.assertAlmostEqual(
            report["totals"]["mass_kg_total"],
            report["totals"]["mass_kg_per_piece"] * 5,
            places=9,
        )
        self.assertAlmostEqual(
            report["totals"]["mass_kg_total_with_waste"],
            report["totals"]["mass_kg_total"] * 1.1,
            places=9,
        )

    def test_job_without_density_keeps_mass_unresolved(self):
        chain = unfold_chain(
            thickness_mm=2.5, radius_mm=1.5, angle_degrees=90.0, k_factor=0.33, segments_mm=[30.0, 40.0, 50.0]
        )
        report = estimate_job(chain, width_mm=400.0, material="unobtanium", quantity=5, thickness_mm=2.5)
        self.assertIsNone(report["totals"]["mass_kg_total"])
        self.assertTrue(any("unresolved" in item for item in report["unresolved"]))

    def test_invalid_quantity_rejected(self):
        with self.assertRaises(EstimateError):
            estimate_labor(2, 0)


if __name__ == "__main__":
    unittest.main()
