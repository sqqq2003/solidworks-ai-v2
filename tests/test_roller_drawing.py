
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
import unittest
from types import SimpleNamespace

from roller_drawing import (
    RollerDrawingVariant,
    decode_solidworks_text,
    extract_roller_variants,
    looks_like_roller_drawing,
)


def _point(x: float, y: float) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y)


def _mtext(x: float, y: float, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        dxftype=lambda: "MTEXT",
        dxf=SimpleNamespace(insert=_point(x, y)),
        plain_text=lambda: text,
    )


def _dimension(
    x: float,
    y: float,
    value: float,
    text: str = "<>",
) -> SimpleNamespace:
    return SimpleNamespace(
        dxftype=lambda: "DIMENSION",
        dxf=SimpleNamespace(
            text=text,
            text_midpoint=_point(x, y),
            defpoint=_point(x, y),
        ),
        get_measurement=lambda: value,
    )


class RollerDrawingExtractionTests(unittest.TestCase):
    def test_conveyor_title_is_not_a_roller_specification(self) -> None:
        entities = (
            _mtext(0, 0, '1.0米无动力滚筒线明细表（单台数量）'),
            _mtext(0, -600, '201不锈钢无动力滚筒-壁厚1.2mm'),
            _dimension(100, -500, 650),
        )
        variants = extract_roller_variants(None, entities)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].overall_length_mm, 650)
        self.assertNotIn('明细表', variants[0].note)

    def test_decodes_solidworks_unicode_escapes(self) -> None:
        self.assertEqual(
            decode_solidworks_text(
                "201\\U+4E0D\\U+9508\\U+94A2\\U+52A8\\U+529B"
            ),
            "201不锈钢动力",
        )

    def test_extracts_powered_roller_from_note_and_nearby_dimensions(self) -> None:
        entities = (
            _mtext(
                0.0,
                0.0,
                "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
            ),
            _mtext(650.0, 180.0, "X 9 支"),
            _dimension(100.0, 80.0, 680.0),
            _dimension(150.0, 110.0, 50.0, "%%c<>"),
            _dimension(220.0, 110.0, 12.0, "%%c<>"),
            _dimension(260.0, 160.0, 18.0),
            _dimension(40.0, 160.0, 5.0),
        )

        variants = extract_roller_variants(None, entities)

        self.assertEqual(len(variants), 1)
        variant = variants[0]
        self.assertIsInstance(variant, RollerDrawingVariant)
        self.assertEqual(variant.roller_type, "动力滚筒")
        self.assertEqual(variant.quantity, 9)
        self.assertEqual(variant.overall_length_mm, 680.0)
        self.assertEqual(variant.outer_diameter_mm, 50.0)
        self.assertEqual(variant.wall_thickness_mm, 1.2)
        self.assertEqual(variant.shaft_diameter_mm, 12.0)
        self.assertEqual(variant.shaft_projection_mm, 18.0)
        self.assertEqual(variant.shaft_exposed_mm, 5.0)
        self.assertEqual(variant.sprocket_teeth, 14)
        self.assertAlmostEqual(variant.chain_pitch_mm, 12.7)
        # 图上没有标螺纹，实现按完整参考件兜底 M10 并如实标记为推断字段；
        # 真实图纸会写 M8/M10（如测试 2 的 "2-M<>-20深"），那时该字段不出现。
        self.assertEqual(
            variant.inferred_fields,
            frozenset({"shaft_thread_designation"}),
        )

    def test_uses_global_diameter_defaults_for_unpowered_variant(self) -> None:
        entities = (
            _mtext(
                0.0,
                0.0,
                "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
            ),
            _dimension(150.0, 110.0, 50.0, "%%c<>"),
            _dimension(220.0, 110.0, 12.0, "%%c<>"),
            _dimension(260.0, 160.0, 18.0),
            _dimension(40.0, 160.0, 5.0),
            _mtext(0.0, -600.0, "201不锈钢无动力滚筒-臂厚1.2mm"),
            _mtext(650.0, -420.0, "X 1 支"),
            _dimension(100.0, -500.0, 500.0),
            _dimension(220.0, -490.0, 12.0, "%%c<>"),
            _dimension(160.0, -450.0, 8.0, "2-M<>-20深"),
        )

        variants = extract_roller_variants(None, entities)

        self.assertEqual(len(variants), 2)
        unpowered = next(
            variant for variant in variants if not variant.is_powered
        )
        self.assertEqual(unpowered.roller_type, "无动力滚筒")
        self.assertEqual(unpowered.quantity, 1)
        self.assertEqual(unpowered.overall_length_mm, 500.0)
        self.assertEqual(unpowered.outer_diameter_mm, 50.0)
        self.assertEqual(unpowered.shaft_diameter_mm, 12.0)
        self.assertEqual(unpowered.shaft_projection_mm, 18.0)
        self.assertEqual(unpowered.shaft_exposed_mm, 5.0)
        self.assertIn("outer_diameter_mm", unpowered.inferred_fields)
        self.assertIn("shaft_projection_mm", unpowered.inferred_fields)


def _roller_variant(note: str) -> RollerDrawingVariant:
    return RollerDrawingVariant(
        roller_type="无动力滚筒",
        quantity=1,
        overall_length_mm=1500.0,
        outer_diameter_mm=50.0,
        wall_thickness_mm=1.5,
        shaft_diameter_mm=12.0,
        shaft_projection_mm=18.0,
        shaft_exposed_mm=5.0,
        sprocket_teeth=None,
        chain_pitch_mm=None,
        note=note,
    )


class RollerDrawingDetectionTests(unittest.TestCase):
    """钣金图里顺带画一根滚筒，不该让整张图走滚筒流程。"""

    def test_sheet_metal_drawing_with_roller_part_stays_sheet_metal(self) -> None:
        # 真实图：0.8米无动力滚筒线_钣金图.dxf，图里画了 Φ50×1500 的滚筒。
        # 文件名带「无动力滚筒」，但它是钣金图，应走钣金流程。
        name = "0.8米无动力滚筒线_钣金图.dxf"
        variants = (_roller_variant("1.0米无动力滚筒"),)

        self.assertFalse(
            looks_like_roller_drawing(variants, bend_count=0, path_name=name)
        )
        self.assertFalse(
            looks_like_roller_drawing(variants, bend_count=4, path_name=name)
        )

    def test_pure_roller_drawing_still_detected(self) -> None:
        # 滚筒尺寸图本身（图名没有钣金/展开字样）仍要判成滚筒图。
        name = "1.3米斜滚筒线滚筒尺寸图.dxf"
        variants = (_roller_variant("1.3米斜滚筒 Φ50×1200"),)

        self.assertTrue(
            looks_like_roller_drawing(variants, bend_count=0, path_name=name)
        )


if __name__ == "__main__":
    unittest.main()
