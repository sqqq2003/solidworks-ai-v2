"""roller_spec：图纸规格 → 建模参数 / 文件名 的规则。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import tempfile
import unittest
from pathlib import Path

from roller_drawing import RollerDrawingVariant
from roller_spec import RollerSpecError, spec_from_variant, variant_filename, variant_label
from solidworks_generator import DEFAULT_SHAFT_THREAD_DESIGNATION


def _variant(**overrides: object) -> RollerDrawingVariant:
    data: dict[str, object] = {
        "roller_type": "动力滚筒",
        "quantity": 2,
        "overall_length_mm": 680.0,
        "outer_diameter_mm": 50.0,
        "wall_thickness_mm": 1.2,
        "shaft_diameter_mm": 12.0,
        "shaft_projection_mm": 18.0,
        "shaft_exposed_mm": 5.0,
        "sprocket_teeth": 14,
        "chain_pitch_mm": 12.7,
        "note": "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
        "shaft_thread_designation": "M10",
        "shaft_step_diameter_mm": 15.0,
    }
    data.update(overrides)
    return RollerDrawingVariant(**data)  # type: ignore[arg-type]


class SpecFromVariantTests(unittest.TestCase):
    def test_powered_variant_keeps_sprocket_and_drops_step_diameter(self) -> None:
        spec = spec_from_variant(_variant())
        self.assertEqual(spec.sprocket_teeth, 14)
        self.assertAlmostEqual(spec.chain_pitch_mm or 0.0, 12.7)
        # 动力滚筒没有轴端台阶这一说，图纸上纵使标了也不该带进去。
        self.assertIsNone(spec.shaft_step_diameter_mm)
        self.assertAlmostEqual(spec.overall_length_mm, 680.0)

    def test_unpowered_variant_drops_sprocket_and_keeps_step(self) -> None:
        spec = spec_from_variant(
            _variant(roller_type="无动力滚筒", sprocket_teeth=None, chain_pitch_mm=None)
        )
        self.assertIsNone(spec.sprocket_teeth)
        self.assertIsNone(spec.chain_pitch_mm)
        self.assertAlmostEqual(spec.shaft_step_diameter_mm or 0.0, 15.0)

    def test_missing_dimensions_raise(self) -> None:
        with self.assertRaises(RollerSpecError):
            spec_from_variant(_variant(overall_length_mm=None))
        with self.assertRaises(RollerSpecError):
            spec_from_variant(_variant(outer_diameter_mm=None))

    def test_missing_optionals_fall_back_to_reference_part(self) -> None:
        spec = spec_from_variant(
            _variant(
                wall_thickness_mm=None,
                shaft_diameter_mm=None,
                shaft_projection_mm=None,
                shaft_thread_designation=None,
            )
        )
        self.assertAlmostEqual(spec.wall_thickness_mm, 1.2)
        self.assertAlmostEqual(spec.shaft_diameter_mm, 12.0)
        self.assertAlmostEqual(spec.shaft_projection_mm, 18.0)
        self.assertEqual(spec.shaft_thread_designation, DEFAULT_SHAFT_THREAD_DESIGNATION)


class VariantFilenameTests(unittest.TestCase):
    def test_name_carries_key_dimensions(self) -> None:
        name = variant_filename(_variant(), "1.0米滚筒线尺寸图")
        self.assertTrue(name.endswith(".SLDPRT"))
        self.assertIn("Φ50x680", name)
        self.assertIn("动力滚筒", name)

    def test_existing_file_gets_a_suffix_instead_of_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = variant_filename(_variant(), "图纸")
            (Path(directory) / first).write_text("x", encoding="utf-8")
            second = variant_filename(
                _variant(), "图纸", existing={Path(first)}
            )
            self.assertNotEqual(first, second)
            self.assertTrue(second.endswith("_2.SLDPRT"))

    def test_illegal_characters_are_replaced(self) -> None:
        name = variant_filename(_variant(), '图纸<>:"/\\|?*')
        for bad in '<>:"/\\|?*':
            self.assertNotIn(bad, name)

    def test_unknown_dimensions_do_not_crash(self) -> None:
        name = variant_filename(_variant(overall_length_mm=None), "图纸")
        self.assertIn("待定", name)


class VariantLabelTests(unittest.TestCase):
    def test_label_mentions_type_and_size(self) -> None:
        label = variant_label(_variant())
        self.assertIn("动力滚筒", label)
        self.assertIn("Φ50", label)
        self.assertIn("680", label)


if __name__ == "__main__":
    unittest.main()
