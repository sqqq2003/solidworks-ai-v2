from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import math
import unittest

from bend_allowance import (
    SW_BEND_ALLOWANCE_DEDUCTION,
    SW_BEND_ALLOWANCE_K_FACTOR,
    compute_bend_allowance,
    flat_length_mm,
    k_factor_from_bend_deduction,
    resolve_bend_allowance_spec,
)


class BendAllowanceTests(unittest.TestCase):
    def test_ninety_degree_soft_steel(self) -> None:
        # t=1.5, R=1.5, K=0.44, 90° — 常见冷轧板。
        result = compute_bend_allowance(1.5, 1.5, 90.0, 0.44)
        # BA = π/2 * (1.5 + 0.44*1.5) = π/2 * 2.16
        self.assertAlmostEqual(result.bend_allowance_mm, math.pi / 2 * 2.16, places=6)
        # OSSB = (1.5+1.5)*tan(45°) = 3
        self.assertAlmostEqual(result.outside_setback_mm, 3.0, places=6)
        # BD = 2*3 - BA
        self.assertAlmostEqual(
            result.bend_deduction_mm,
            6.0 - result.bend_allowance_mm,
            places=6,
        )
        self.assertGreater(result.deduction_factor, 1.5)
        self.assertLess(result.deduction_factor, 1.9)

    def test_k_factor_round_trip_from_deduction(self) -> None:
        thickness, radius, angle, k_factor = 2.0, 2.0, 90.0, 0.40
        result = compute_bend_allowance(thickness, radius, angle, k_factor)
        recovered = k_factor_from_bend_deduction(
            thickness, radius, angle, result.bend_deduction_mm
        )
        self.assertAlmostEqual(recovered, k_factor, places=6)

    def test_flat_length_uses_deduction(self) -> None:
        # 两边各 50，量到尖角；扣除 3.2 → 展开 96.8
        self.assertAlmostEqual(flat_length_mm(50.0, 50.0, 3.2), 96.8, places=6)

    def test_resolve_bend_deduction_mode(self) -> None:
        spec, result = resolve_bend_allowance_spec(
            thickness_mm=1.2,
            radius_mm=1.2,
            angle_degrees=90.0,
            mode="bend_deduction",
            k_factor=0.44,
            bend_deduction_mm=2.05,
        )
        self.assertEqual(spec.mode, "bend_deduction")
        self.assertEqual(spec.sw_type, SW_BEND_ALLOWANCE_DEDUCTION)
        self.assertAlmostEqual(spec.bend_deduction_mm or 0.0, 2.05, places=6)
        self.assertAlmostEqual(result.bend_deduction_mm, 2.05, places=6)

    def test_resolve_k_factor_mode(self) -> None:
        spec, result = resolve_bend_allowance_spec(
            thickness_mm=1.0,
            radius_mm=1.0,
            angle_degrees=90.0,
            mode="k_factor",
            k_factor=0.5,
        )
        self.assertEqual(spec.sw_type, SW_BEND_ALLOWANCE_K_FACTOR)
        self.assertAlmostEqual(spec.k_factor, 0.5, places=6)
        self.assertAlmostEqual(
            result.bend_allowance_mm,
            math.pi / 2 * (1.0 + 0.5 * 1.0),
            places=6,
        )

    def test_rejects_bad_angle(self) -> None:
        with self.assertRaises(ValueError):
            compute_bend_allowance(1.0, 1.0, 0.0, 0.44)
        with self.assertRaises(ValueError):
            compute_bend_allowance(1.0, 1.0, 180.0, 0.44)


if __name__ == "__main__":
    unittest.main()
