"""No silent t/R/K defaults on the sheet-metal bend path (issue #25 follow-up).

Rule (user, 2026-10-24, twice emphasized): plate thickness t and the K factor
are NEVER constants -- every job differs (material, thickness, die V-opening,
inner radius, process), so t and K must be computed per job from that job's
inputs. t=2.5 / R=1 / K=0.36 / BA=3.0 / BD=4.0 is one factory measured case
(2026-10-22 symmetric U-channel), not defaults. Missing inputs must surface
as pending_confirmation, never as a substituted default number.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src")]

import ezdxf
from bend_allowance import BendAllowanceSpec, compute_bend_allowance
from cad_analyzer import analyze_dxf
from k_factor_evidence import audit_variants
from sheet_metal_pipeline import build_plan

EVIDENCE = {
    "variants": [
        {"k_target": 0.5, "k_read": 0.5,
         "dxf_extents": {"ok": True, "max_extent_mm": 431.004}},
        {"k_target": 0.25, "k_read": 0.25,
         "dxf_extents": {"ok": True, "max_extent_mm": 431.004}},
    ]
}


class NoDefaultKTests(unittest.TestCase):
    def test_spec_construction_requires_explicit_k(self):
        # Previously BendAllowanceSpec('k_factor') silently used k_factor=0.44.
        with self.assertRaises(TypeError):
            BendAllowanceSpec("k_factor")
        spec = BendAllowanceSpec("k_factor", k_factor=0.36)
        self.assertEqual(spec.k_factor, 0.36)

    def test_explicit_k_ba_bd_math(self):
        # Factory measured case, used here as one explicit fixture, not a default.
        result = compute_bend_allowance(2.5, 1.0, 90.0, 0.36)
        self.assertAlmostEqual(result.bend_allowance_mm, 2.9845, places=3)
        self.assertAlmostEqual(result.bend_deduction_mm, 4.0155, places=3)
        # One non-factory parameter set, proving the math is parameter-driven.
        other = compute_bend_allowance(3.0, 2.0, 90.0, 0.40)
        self.assertAlmostEqual(other.bend_allowance_mm, 5.0265, places=3)
        self.assertAlmostEqual(other.bend_deduction_mm, 4.9735, places=3)

    def test_audit_variants_requires_explicit_geometry(self):
        # Previously audit_variants() silently used thickness 2.5 / radius 1 / 90 deg.
        with self.assertRaises(TypeError):
            audit_variants(EVIDENCE)
        with self.assertRaises(TypeError):
            audit_variants(EVIDENCE, geometry_basis="fixed_blank")
        fixed = audit_variants(
            EVIDENCE, geometry_basis="fixed_blank",
            thickness_mm=2.5, radius_mm=1, angle_degrees=90,
        )
        self.assertEqual(
            fixed["status"], "consistent_fixed_blank_pending_folded_measurements"
        )

    def test_build_plan_without_k_is_pending_not_computed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "synthetic.dxf"
            doc = ezdxf.new("R2010")
            doc.units = ezdxf.units.MM
            space = doc.modelspace()
            space.add_lwpolyline([(0, 0), (100, 0), (100, 80), (0, 80)], close=True)
            doc.layers.new("BEND", dxfattribs={"color": 1})
            space.add_line((50, 0), (50, 80),
                           dxfattribs={"layer": "BEND", "color": 1})
            doc.saveas(source)
            analysis = analyze_dxf(source)
            outer = max(
                range(len(analysis.profiles)),
                key=lambda i: len(analysis.profiles[i].points)
                if analysis.profiles[i].kind != "CIRCLE" else 0,
            )
            plan = build_plan(
                analysis, profile_index=outer,
                thickness_mm=2.5, radius_mm=1, angle_degrees=90,
                k_factor=None, flip_direction=False, bends_confirmed=True,
            )
            self.assertIn("k_factor", plan["pending"])
            self.assertIsNone(plan["bend_allowance"])
            self.assertEqual(plan["status"], "pending")

    def test_no_default_constants_in_bend_modules(self):
        root = Path(__file__).resolve().parents[1] / "src"
        for name in ("bend_allowance.py", "k_factor_evidence.py",
                     "sheet_metal_pipeline.py", "sheet_metal_windows.py"):
            src = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("DEFAULT_K", src, name)
            self.assertNotIn("DEFAULT_T", src, name)
            self.assertNotIn("MATERIAL_K_FACTORS", src, name)


if __name__ == "__main__":
    unittest.main()
