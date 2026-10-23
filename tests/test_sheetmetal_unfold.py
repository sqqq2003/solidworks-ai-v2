"""Issue #6 module 4: sheet-metal unfold / relief / K-factor interface tests."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from src.sheetmetal_unfold import (
    generation_request,
    k_factor_options,
    relief_plan,
    unfold_chain,
    unfold_plan,
)


class UnfoldPlanTests(unittest.TestCase):
    def test_known_numbers_for_2_5mm_1r_90deg(self):
        plan = unfold_plan(
            thickness_mm=2.5,
            radius_mm=1.0,
            angle_degrees=90.0,
            k_factor=0.4,
            legs_mm=(50.0, 30.0),
        )
        bend = plan["bend"]
        self.assertAlmostEqual(bend["bend_allowance_mm"], math.pi / 2 * (1.0 + 0.4 * 2.5))
        self.assertAlmostEqual(bend["outside_setback_mm"], 3.5)
        self.assertAlmostEqual(bend["bend_deduction_mm"], 2 * 3.5 - bend["bend_allowance_mm"])
        self.assertAlmostEqual(bend["flat_length_mm"], 80.0 - bend["bend_deduction_mm"])
        self.assertAlmostEqual(bend["deduction_factor"], bend["bend_deduction_mm"] / 2.5)
        self.assertEqual(plan["backend"], "offline_python")
        self.assertFalse(plan["cad_executed"])
        self.assertEqual(plan["sw_live"], "not_applicable_on_linux")

    def test_bend_allowance_spec_matches_sw_enum(self):
        plan = unfold_plan(
            thickness_mm=2.0,
            radius_mm=1.0,
            angle_degrees=90.0,
            k_factor=0.44,
            legs_mm=(40.0, 40.0),
        )
        spec = plan["bend_allowance_spec"]
        self.assertEqual(spec["mode"], "k_factor")
        self.assertEqual(spec["sw_type"], 2)  # swBendAllowanceKFactor
        self.assertIn("BD", plan["summary"])

    def test_deduction_mode_uses_shop_number(self):
        plan = unfold_plan(
            thickness_mm=2.0,
            radius_mm=1.0,
            angle_degrees=90.0,
            k_factor=0.44,
            legs_mm=(40.0, 40.0),
            mode="bend_deduction",
            bend_deduction_mm=3.5,
        )
        self.assertEqual(plan["bend_allowance_spec"]["mode"], "bend_deduction")
        self.assertAlmostEqual(plan["bend"]["bend_deduction_mm"], 3.5)
        self.assertAlmostEqual(plan["bend"]["flat_length_mm"], 80.0 - 3.5)

    def test_invalid_inputs_rejected(self):
        base = dict(
            thickness_mm=2.0,
            radius_mm=1.0,
            angle_degrees=90.0,
            k_factor=0.4,
            legs_mm=(10.0, 10.0),
        )
        with self.assertRaises(ValueError):
            unfold_plan(**{**base, "angle_degrees": 0.0})
        with self.assertRaises(ValueError):
            unfold_plan(**{**base, "k_factor": 1.5})
        with self.assertRaises(ValueError):
            unfold_plan(**{**base, "legs_mm": (-1.0, 10.0)})
        with self.assertRaises(ValueError):
            unfold_plan(**{**base, "legs_mm": (10.0,)})

    def test_unfold_chain_sums_deductions(self):
        plan = unfold_chain(
            thickness_mm=2.5,
            radius_mm=1.0,
            angle_degrees=90.0,
            k_factor=0.4,
            segments_mm=(40.0, 40.0, 40.0),
        )
        self.assertEqual(plan["bend_count"], 2)
        per_bend = math.pi / 2 * (1.0 + 0.4 * 2.5)
        ossb = (1.0 + 2.5) * math.tan(math.radians(45))
        bd = 2 * ossb - per_bend
        self.assertAlmostEqual(plan["total_bend_deduction_mm"], 2 * bd)
        self.assertAlmostEqual(plan["flat_length_mm"], 120.0 - 2 * bd)
        with self.assertRaises(ValueError):
            unfold_chain(
                thickness_mm=2.5,
                radius_mm=1.0,
                angle_degrees=90.0,
                k_factor=0.4,
                segments_mm=(40.0,),
            )


class ReliefPlanTests(unittest.TestCase):
    def test_relief_sizes_follow_craft_rules(self):
        plan = relief_plan(thickness_mm=2.0, radius_mm=1.0, relief_step=0)
        self.assertEqual(plan["width_mm"], 2.0)  # k >= t
        self.assertAlmostEqual(plan["depth_past_centerline_mm"], 3.5)  # t + R + 0.5
        self.assertEqual(plan["expand_up_mm"], 0.0)
        self.assertEqual(plan["expand_inward_mm"], 0.0)
        self.assertEqual(plan["max_relief_steps"], 2)
        self.assertFalse(plan["cad_executed"])

    def test_relief_expansion_steps(self):
        step1 = relief_plan(thickness_mm=2.0, radius_mm=1.0, relief_step=1)
        self.assertAlmostEqual(step1["expand_up_mm"], 1.0)
        self.assertAlmostEqual(step1["expand_inward_mm"], 1.0)
        step2 = relief_plan(thickness_mm=2.0, radius_mm=1.0, relief_step=2)
        self.assertAlmostEqual(step2["expand_up_mm"], 1.5)

    def test_relief_step_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            relief_plan(thickness_mm=2.0, radius_mm=1.0, relief_step=3)
        with self.assertRaises(ValueError):
            relief_plan(thickness_mm=2.0, radius_mm=1.0, relief_step=-1)

    def test_k_factor_options_come_from_bend_allowance(self):
        options = k_factor_options()
        self.assertEqual(options["不锈钢"], 0.40)
        self.assertEqual(options["软钢/冷轧"], 0.44)


class GenerationRequestTests(unittest.TestCase):
    def test_request_describes_existing_generator_without_calling_it(self):
        request = generation_request(
            thickness_mm=2.5,
            radius_mm=1.0,
            angle_degrees=90.0,
            k_factor=0.4,
            profile_index=0,
            bend_indices=(0, 1),
            output_path="D:/out/part.SLDPRT",
        )
        self.assertEqual(request["entry"], "solidworks_generator.generate_sheet_metal")
        self.assertEqual(request["hook"], "a01_next.sheet_metal_hook.sheet_metal_hook")
        self.assertFalse(request["called"])
        self.assertFalse(request["cad_executed"])
        self.assertEqual(request["sw_live"], "not_applicable_on_linux")
        kwargs = request["kwargs"]
        self.assertEqual(kwargs["profile_index"], 0)
        self.assertEqual(kwargs["bend_indices"], [0, 1])
        self.assertEqual(kwargs["relief_bend_indices"], [0, 1])
        self.assertEqual(kwargs["bend_allowance"]["sw_type"], 2)
        self.assertIsNone(kwargs["analysis"])

    def test_request_records_analysis_supplier(self):
        request = generation_request(
            thickness_mm=2.5,
            radius_mm=1.0,
            angle_degrees=90.0,
            k_factor=0.4,
            profile_index=3,
            bend_indices=(),
            output_path="D:/out/part.SLDPRT",
            analysis=object(),
        )
        self.assertEqual(request["kwargs"]["analysis"], "<DrawingAnalysis supplied by caller>")


if __name__ == "__main__":
    unittest.main()
