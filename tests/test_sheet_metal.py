from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import math
import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_analyzer import (
    DrawingAnalysis,
    Primitive,
    SketchSegment,
    _line_contours,
    analyze_dxf,
    is_manual_bend_candidate,
    primitive_bounds,
)
from profile_edit import resize_profile_dimensions
from profile_selection import (
    candidate_profile_indices,
    contained_hole_indices,
    point_hits_profile,
)
from roller_drawing import (
    extract_roller_variants,
    extract_roller_variants_from_filename,
    looks_like_roller_drawing,
    _length_from_text,
    _parse_note,
)


def _line(start: tuple[float, float], end: tuple[float, float]) -> Primitive:
    return Primitive(
        (start, end),
        False,
        False,
        "0",
        "LINE",
        (SketchSegment(start, end),),
    )


class ContourJoinTests(unittest.TestCase):
    def test_gapped_rectangle_lines_form_contour(self) -> None:
        # 四条边端点各留约 0.2 mm 缝，模拟 DWG 导出误差。
        gap = 0.2
        edges = (
            _line((0.0, 0.0), (100.0 - gap, 0.0)),
            _line((100.0, gap), (100.0, 50.0 - gap)),
            _line((100.0 - gap, 50.0), (gap, 50.0)),
            _line((0.0, 50.0 - gap), (0.0, gap)),
        )
        contours = _line_contours(edges)
        self.assertEqual(len(contours), 1)
        self.assertTrue(contours[0].closed)
        min_x, min_y, max_x, max_y = primitive_bounds(contours[0])
        self.assertAlmostEqual(max_x - min_x, 100.0, delta=0.5)
        self.assertAlmostEqual(max_y - min_y, 50.0, delta=0.5)

    def test_dangling_stub_does_not_block_contour(self) -> None:
        edges = (
            _line((0.0, 0.0), (80.0, 0.0)),
            _line((80.0, 0.0), (80.0, 40.0)),
            _line((80.0, 40.0), (0.0, 40.0)),
            _line((0.0, 40.0), (0.0, 0.0)),
            # 尺寸引出线：挂在轮廓上却不成环。
            _line((40.0, 0.0), (40.0, -8.0)),
        )
        contours = _line_contours(edges)
        self.assertEqual(len(contours), 1)
        self.assertTrue(contours[0].closed)

    def test_open_polyline_edges_join_into_contour(self) -> None:
        poly = Primitive(
            ((0.0, 0.0), (60.0, 0.0), (60.0, 30.0)),
            False,
            False,
            "0",
            "LWPOLYLINE",
            (
                SketchSegment((0.0, 0.0), (60.0, 0.0)),
                SketchSegment((60.0, 0.0), (60.0, 30.0)),
            ),
        )
        closer = (
            _line((60.0, 30.0), (0.0, 30.0)),
            _line((0.0, 30.0), (0.0, 0.0)),
        )
        contours = _line_contours((poly, *closer))
        self.assertEqual(len(contours), 1)
        self.assertTrue(contours[0].closed)

    def test_straight_polyline_is_manual_bend_candidate(self) -> None:
        poly = Primitive(
            ((0.0, 10.0), (25.0, 10.0), (50.0, 10.0)),
            False,
            False,
            "0",
            "LWPOLYLINE",
            (
                SketchSegment((0.0, 10.0), (25.0, 10.0)),
                SketchSegment((25.0, 10.0), (50.0, 10.0)),
            ),
        )
        self.assertTrue(is_manual_bend_candidate(poly))


class BendDetectionDxFTests(unittest.TestCase):
    def test_bend_layer_red_solid_is_detected(self) -> None:
        doc = ezdxf.new()
        doc.layers.add("折弯线", color=1)
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (100, 0), (100, 40), (0, 40)],
            close=True,
            dxfattribs={"layer": "0", "color": 7},
        )
        # 折弯图层上的红色实线（线型未导出为虚线）也应识别。
        msp.add_line(
            (30, 0),
            (30, 40),
            dxfattribs={"layer": "折弯线", "color": 1, "linetype": "Continuous"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bend_layer.dxf"
            doc.saveas(path)
            analysis = analyze_dxf(path)
        self.assertGreaterEqual(len(analysis.profiles), 1)
        self.assertEqual(len(analysis.bend_lines), 1)

    def test_near_closed_polyline_becomes_profile(self) -> None:
        doc = ezdxf.new()
        msp = doc.modelspace()
        # 首尾留缝的开放多段线，应自动闭合为轮廓。
        msp.add_lwpolyline(
            [(0, 0), (120, 0), (120, 55), (0, 55), (0, 0.02)],
            close=False,
            dxfattribs={"layer": "0", "color": 7},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "near_closed.dxf"
            doc.saveas(path)
            analysis = analyze_dxf(path)
        self.assertGreaterEqual(len(analysis.profiles), 1)
        self.assertTrue(analysis.profiles[0].closed)


class RollerDrawingRoutingTests(unittest.TestCase):
    def test_looks_like_roller_when_variants_present(self) -> None:
        from roller_drawing import RollerDrawingVariant

        variants = (
            RollerDrawingVariant(
                "动力滚筒",
                4,
                280.0,
                50.0,
                1.2,
                12.0,
                13.5,
                5.0,
                14,
                12.7,
                "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
                shaft_thread_designation="M10",
            ),
        )
        self.assertTrue(
            looks_like_roller_drawing(variants, bend_count=0, path_name="x.dxf")
        )

    def test_roller_frame_sheet_metal_not_routed_as_roller(self) -> None:
        """带「滚筒」字样的滚筒架/组织架钣金应走钣金，而不是滚筒零件。"""

        for name in (
            "组织滚筒架.dwg",
            "滚筒支架钣金展开图.dxf",
            "1.3米滚筒架侧板.dwg",
            "滚筒机架焊板.dxf",
        ):
            variants = extract_roller_variants_from_filename(name)
            self.assertEqual(variants, (), msg=name)
            self.assertFalse(
                looks_like_roller_drawing((), bend_count=0, path_name=name),
                msg=name,
            )
            self.assertFalse(
                looks_like_roller_drawing((), bend_count=3, path_name=name),
                msg=name,
            )

        roller_type, *_rest = _parse_note("组织滚筒架-不锈钢侧板")
        self.assertIsNone(roller_type)

    def test_bend_lines_prefer_sheet_metal_without_roller_callout(self) -> None:
        from roller_drawing import RollerDrawingVariant

        weak = (
            RollerDrawingVariant(
                "无动力滚筒",
                1,
                1300.0,
                50.0,
                1.2,
                12.0,
                13.5,
                5.0,
                None,
                None,
                "零件总成含滚筒",
            ),
        )
        self.assertFalse(
            looks_like_roller_drawing(
                weak,
                bend_count=2,
                path_name="零件总成.dxf",
            )
        )

    def test_parse_slanted_roller_note(self) -> None:
        roller_type, wall, teeth, pitch = _parse_note(
            "斜滚筒线专用 不锈钢斜滚筒-臂厚1.2mm"
        )
        self.assertEqual(roller_type, "无动力滚筒")
        self.assertEqual(wall, 1.2)
        self.assertIsNone(teeth)
        self.assertAlmostEqual(_length_from_text("1.3米斜滚筒线滚筒尺寸图"), 1300.0)

    def test_analyze_cad_file_dwg_failure_uses_filename(self) -> None:
        from unittest.mock import patch

        from cad_analyzer import analyze_cad_file
        from dwg_converter import DwgConversionError

        name = "1.3米斜滚筒线滚筒尺寸图（斜滚筒线专用）(1).dwg"

        def boom(_source: Path, _target: Path) -> None:
            raise DwgConversionError("SolidWorks 未能导入此 DWG 文件。")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_bytes(b"not-a-real-dwg")
            with patch(
                "cad_analyzer.iter_dwg_converters",
                return_value=(("solidworks", boom),),
            ):
                analysis = analyze_cad_file(path)
        self.assertEqual(analysis.layout_name, "文件名回退")
        self.assertEqual(len(analysis.roller_variants), 1)
        self.assertAlmostEqual(
            analysis.roller_variants[0].overall_length_mm or 0.0, 1300.0
        )

    def test_drawing1_dwg_prefers_converter_with_roller_notes(self) -> None:
        """Drawing1.dwg：SolidWorks 空结果时，应改用带滚筒注记的 LibreDWG 结果。"""

        from unittest.mock import patch

        from cad_analyzer import analyze_cad_file

        empty_doc = ezdxf.new()
        empty_doc.units = ezdxf.units.MM
        empty_doc.modelspace().add_line((0, 0), (10, 0))

        rich_doc = ezdxf.new()
        rich_doc.units = ezdxf.units.MM
        msp = rich_doc.modelspace()
        msp.add_mtext(
            "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
            dxfattribs={"insert": (0, 0), "char_height": 5},
        )
        msp.add_linear_dim(
            base=(0, 40),
            p1=(0, 0),
            p2=(280, 0),
            dimstyle="EZDXF",
        ).render()
        msp.add_diameter_dim(
            center=(40, -30),
            radius=25,
            angle=45,
            dimstyle="EZDXF",
        ).render()
        msp.add_diameter_dim(
            center=(40, -60),
            radius=6,
            angle=45,
            dimstyle="EZDXF",
        ).render()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            empty_dxf = tmp_path / "empty.dxf"
            rich_dxf = tmp_path / "rich.dxf"
            empty_doc.saveas(empty_dxf)
            rich_doc.saveas(rich_dxf)
            dwg_path = tmp_path / "Drawing1.dwg"
            dwg_path.write_bytes(b"fake-dwg")

            def fake_sw(source: Path, target: Path) -> None:
                target.write_bytes(empty_dxf.read_bytes())

            def fake_libredwg(source: Path, target: Path) -> None:
                target.write_bytes(rich_dxf.read_bytes())

            with patch(
                "cad_analyzer.iter_dwg_converters",
                return_value=(
                    ("solidworks", fake_sw),
                    ("libredwg", fake_libredwg),
                ),
            ):
                analysis = analyze_cad_file(dwg_path)

        self.assertEqual(analysis.path.name, "Drawing1.dwg")
        self.assertGreaterEqual(len(analysis.roller_variants), 1)
        self.assertEqual(analysis.roller_variants[0].roller_type, "动力滚筒")
        self.assertTrue(
            looks_like_roller_drawing(
                analysis.roller_variants,
                bend_count=0,
                path_name="Drawing1.dwg",
            )
        )

    def test_drawing1_real_dwg_renamed_still_finds_rollers(self) -> None:
        """真实滚筒 DWG 即使改名为 Drawing1.dwg 也应识别出规格。"""

        from cad_analyzer import analyze_cad_file

        uploads = Path(
            "/home/ubuntu/.cursor/projects/workspace/uploads/1.3___________________1__3e77.dwg"
        )
        if not uploads.is_file():
            self.skipTest("测试用滚筒 DWG 不在 uploads")
        with tempfile.TemporaryDirectory() as tmp:
            renamed = Path(tmp) / "Drawing1.dwg"
            renamed.write_bytes(uploads.read_bytes())
            analysis = analyze_cad_file(renamed)
        self.assertGreaterEqual(len(analysis.roller_variants), 1)
        self.assertTrue(
            looks_like_roller_drawing(
                analysis.roller_variants,
                bend_count=len(analysis.bend_lines),
                path_name="Drawing1.dwg",
            )
        )

    def test_side_view_geometry_without_notes_finds_rollers(self) -> None:
        """无「滚筒」文字时，仍可从侧视块几何识别动力/无动力规格。"""

        from roller_drawing import extract_roller_variants

        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        unpowered = doc.blocks.new("side_unpowered_260")
        unpowered.add_line((0, 0), (260, 0))
        unpowered.add_line((0, 50), (260, 50))
        unpowered.add_line((0, 25), (260, 25))
        unpowered.add_line((0, 19), (0, 31))
        unpowered.add_line((260, 19), (260, 31))
        unpowered.add_line((13.5, 0), (13.5, 50))
        unpowered.add_line((246.5, 0), (246.5, 50))
        for index in range(12):
            unpowered.add_line((20 + index * 18, 8), (20 + index * 18, 42))

        powered = doc.blocks.new("side_powered_360")
        powered.add_line((0, 0), (360, 0))
        powered.add_line((0, 50), (360, 50))
        powered.add_line((0, 25), (360, 25))
        powered.add_line((0, 19), (0, 31))
        powered.add_line((360, 19), (360, 31))
        powered.add_line((13.5, 0), (13.5, 50))
        powered.add_line((346.5, 0), (346.5, 50))
        for index in range(200):
            powered.add_line((15 + index * 1.5, 5), (15 + index * 1.5, 45))
        for index in range(14):
            powered.add_spline([(350, 25), (355, 30 + index), (360, 25)])

        msp = doc.modelspace()
        msp.add_blockref("side_unpowered_260", insert=(0, 0))
        msp.add_blockref("side_powered_360", insert=(0, 200))

        variants = extract_roller_variants(doc, msp)
        self.assertEqual(len(variants), 2)
        by_type = {variant.roller_type: variant for variant in variants}
        self.assertIn("无动力滚筒", by_type)
        self.assertIn("动力滚筒", by_type)
        self.assertAlmostEqual(by_type["无动力滚筒"].overall_length_mm or 0.0, 260.0)
        self.assertAlmostEqual(by_type["动力滚筒"].overall_length_mm or 0.0, 360.0)
        self.assertAlmostEqual(by_type["无动力滚筒"].outer_diameter_mm or 0.0, 50.0)
        self.assertEqual(by_type["动力滚筒"].sprocket_teeth, 14)
        self.assertTrue(
            looks_like_roller_drawing(variants, bend_count=0, path_name="Drawing1.dwg")
        )

    def test_uploaded_drawing1_dwg_finds_seven_rollers(self) -> None:
        """用户 Drawing1.dwg：无文字注记，侧视几何应识别 7 种滚筒。"""

        from cad_analyzer import analyze_cad_file
        from solidworks_generator import (
            RollerSpec,
            compute_roller_layout,
            validate_roller_spec,
        )

        uploads = Path(
            "/home/ubuntu/.cursor/projects/workspace/uploads/Drawing1_e7b7.dwg"
        )
        if not uploads.is_file():
            self.skipTest("Drawing1_e7b7.dwg 未上传")
        analysis = analyze_cad_file(uploads)
        self.assertEqual(len(analysis.roller_variants), 7)
        self.assertTrue(
            looks_like_roller_drawing(
                analysis.roller_variants,
                bend_count=0,
                path_name="Drawing1.dwg",
            )
        )
        lengths = sorted(
            variant.overall_length_mm or 0.0 for variant in analysis.roller_variants
        )
        self.assertEqual(
            [round(value) for value in lengths],
            [260, 360, 620, 720, 970, 1070, 1350],
        )
        powered = [
            variant
            for variant in analysis.roller_variants
            if variant.roller_type == "动力滚筒"
        ]
        unpowered = [
            variant
            for variant in analysis.roller_variants
            if variant.roller_type == "无动力滚筒"
        ]
        self.assertEqual(len(powered), 4)
        self.assertEqual(len(unpowered), 3)
        for variant in analysis.roller_variants:
            spec = RollerSpec(
                roller_type=variant.roller_type,
                overall_length_mm=float(variant.overall_length_mm or 0.0),
                outer_diameter_mm=float(variant.outer_diameter_mm or 50.0),
                wall_thickness_mm=float(variant.wall_thickness_mm or 1.2),
                shaft_diameter_mm=float(variant.shaft_diameter_mm or 12.0),
                shaft_projection_mm=float(variant.shaft_projection_mm or 13.5),
                sprocket_teeth=variant.sprocket_teeth,
                chain_pitch_mm=variant.chain_pitch_mm,
                shaft_exposed_mm=variant.shaft_exposed_mm,
                shaft_thread_designation=variant.shaft_thread_designation or "M10",
                shaft_step_diameter_mm=variant.shaft_step_diameter_mm,
            )
            validate_roller_spec(spec)
            compute_roller_layout(spec)

    def test_filename_fallback_for_slanted_roller_dwg(self) -> None:
        name = "1.3米斜滚筒线滚筒尺寸图（斜滚筒线专用）(1).dwg"
        variants = extract_roller_variants_from_filename(name)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].roller_type, "无动力滚筒")
        self.assertAlmostEqual(variants[0].overall_length_mm or 0.0, 1300.0)
        self.assertTrue(
            looks_like_roller_drawing(variants, bend_count=0, path_name=name)
        )

        # 图内无注记时，analyze_dxf 也应靠文件名给出规格。
        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        doc.modelspace().add_line((0, 0), (10, 0))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name.replace(".dwg", ".dxf")
            doc.saveas(path)
            analysis = analyze_dxf(path)
        self.assertGreaterEqual(len(analysis.roller_variants), 1)
        self.assertAlmostEqual(
            analysis.roller_variants[0].overall_length_mm or 0.0, 1300.0
        )

    def test_extract_slanted_roller_from_title_and_note(self) -> None:
        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()
        msp.add_mtext(
            "1.3米斜滚筒线滚筒尺寸图（斜滚筒线专用）",
            dxfattribs={"insert": (0, 200), "char_height": 5},
        )
        msp.add_mtext(
            "201不锈钢斜滚筒-臂厚1.2mm",
            dxfattribs={"insert": (0, 0), "char_height": 5},
        )
        # 尺寸离注记较远，模拟斜滚筒布置。
        msp.add_linear_dim(
            base=(0, -350),
            p1=(0, -380),
            p2=(1300, -380),
            dimstyle="EZDXF",
        ).render()
        msp.add_diameter_dim(
            center=(50, -200),
            radius=25,
            angle=45,
            dimstyle="EZDXF",
        ).render()
        variants = extract_roller_variants(doc, msp, scale=1.0)
        self.assertGreaterEqual(len(variants), 1)
        self.assertEqual(variants[0].roller_type, "无动力滚筒")
        self.assertAlmostEqual(variants[0].overall_length_mm or 0.0, 1300.0, places=3)
        self.assertTrue(
            looks_like_roller_drawing(
                variants,
                bend_count=0,
                path_name="1.3米斜滚筒线滚筒尺寸图（斜滚筒线专用）(1).dwg",
            )
        )

    def test_brief_sketch_prefers_dimension_override_text(self) -> None:
        """简略草图：尺寸覆盖字 ``700`` / ``%%C12`` 优先于错误测量值。"""

        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        block = doc.blocks.new("ROLLER_SKETCH")
        block.add_mtext(
            "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
            dxfattribs={"insert": (0, 0), "char_height": 5},
        )
        block.add_mtext(
            "X 13 支",
            dxfattribs={"insert": (400, 40), "char_height": 5},
        )
        # 覆盖文字写 700，测量几何却只有 655——应以 700 为准。
        dim_len = block.add_linear_dim(
            base=(0, 80),
            p1=(0, 0),
            p2=(655, 0),
            dimstyle="EZDXF",
        )
        dim_len.dimension.dxf.text = "700"
        dim_len.render()
        dim_od = block.add_diameter_dim(
            center=(50, -40),
            radius=25,
            angle=45,
            dimstyle="EZDXF",
        )
        dim_od.dimension.dxf.text = "%%C50"
        dim_od.render()
        # 轴径覆盖 %%C12，但圆半径画成 7.5（测量 15）——应以 12 为准。
        dim_shaft = block.add_diameter_dim(
            center=(200, -40),
            radius=7.5,
            angle=30,
            dimstyle="EZDXF",
        )
        dim_shaft.dimension.dxf.text = "%%C12"
        dim_shaft.render()
        block.add_mtext(
            "2-M8-20",
            dxfattribs={"insert": (-80, 20), "char_height": 4},
        )
        doc.modelspace().add_blockref("ROLLER_SKETCH", insert=(0, 0))

        variants = extract_roller_variants(doc, doc.modelspace(), scale=1.0)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].quantity, 13)
        self.assertAlmostEqual(variants[0].overall_length_mm or 0.0, 700.0, places=3)
        self.assertAlmostEqual(variants[0].outer_diameter_mm or 0.0, 50.0, places=3)
        self.assertAlmostEqual(variants[0].shaft_diameter_mm or 0.0, 12.0, places=3)
        self.assertEqual(variants[0].shaft_thread_designation, "M8")
        self.assertEqual(variants[0].sprocket_teeth, 14)

    def test_length_rescued_from_nearby_text_when_override_stripped(self) -> None:
        """SolidWorks 导出丢掉覆盖字后，测量 655 旁若有文字 700 仍应读 700。"""

        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()
        msp.add_mtext(
            "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
            dxfattribs={"insert": (0, 0), "char_height": 5},
        )
        dim_len = msp.add_linear_dim(
            base=(0, 80),
            p1=(0, 0),
            p2=(655, 0),
            dimstyle="EZDXF",
        )
        dim_len.dimension.dxf.text = ""
        dim_len.render()
        # 尺寸中点附近残留设计值文字（覆盖字被导出剥掉时常见）。
        msp.add_text(
            "700",
            dxfattribs={"insert": (327.5, 80), "height": 4},
        )
        msp.add_mtext(
            "%%C50",
            dxfattribs={"insert": (40, -30), "char_height": 4},
        )
        variants = extract_roller_variants(doc, msp, scale=1.0)
        self.assertEqual(len(variants), 1)
        self.assertAlmostEqual(variants[0].overall_length_mm or 0.0, 700.0, places=3)

    def test_length_reads_dimension_geometry_block_label(self) -> None:
        """覆盖字清空时，仍可读 DIMENSION 匿名块里图画的 ``700``（测量仍是 655）。"""

        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()
        msp.add_mtext(
            "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
            dxfattribs={"insert": (0, 0), "char_height": 5},
        )
        dim_len = msp.add_linear_dim(
            base=(0, 80),
            p1=(0, 0),
            p2=(655, 0),
            dimstyle="EZDXF",
        )
        dim_len.dimension.dxf.text = ""
        dim_len.render()
        geometry_name = dim_len.dimension.dxf.get("geometry")
        self.assertTrue(geometry_name)
        # 模拟图面标注块仍写设计值，实体覆盖字已被剥掉。
        block = doc.blocks.get(geometry_name)
        for entity in list(block):
            if entity.dxftype() in ("TEXT", "MTEXT"):
                block.delete_entity(entity)
        block.add_text("700", dxfattribs={"insert": (327.5, 80), "height": 3.5})
        dim_od = msp.add_diameter_dim(
            center=(50, -40),
            radius=25,
            angle=45,
            dimstyle="EZDXF",
        )
        dim_od.dimension.dxf.text = ""
        dim_od.render()
        od_geo = dim_od.dimension.dxf.get("geometry")
        od_block = doc.blocks.get(od_geo)
        for entity in list(od_block):
            if entity.dxftype() in ("TEXT", "MTEXT"):
                od_block.delete_entity(entity)
        od_block.add_text("Ø50", dxfattribs={"insert": (50, -40), "height": 3})
        dim_shaft = msp.add_diameter_dim(
            center=(200, -40),
            radius=7.5,
            angle=30,
            dimstyle="EZDXF",
        )
        dim_shaft.dimension.dxf.text = ""
        dim_shaft.render()
        shaft_geo = dim_shaft.dimension.dxf.get("geometry")
        shaft_block = doc.blocks.get(shaft_geo)
        for entity in list(shaft_block):
            if entity.dxftype() in ("TEXT", "MTEXT"):
                shaft_block.delete_entity(entity)
        shaft_block.add_text("Ø12", dxfattribs={"insert": (200, -40), "height": 3})

        variants = extract_roller_variants(doc, msp, scale=1.0)
        self.assertEqual(len(variants), 1)
        self.assertAlmostEqual(variants[0].overall_length_mm or 0.0, 700.0, places=3)
        self.assertAlmostEqual(variants[0].outer_diameter_mm or 0.0, 50.0, places=3)
        self.assertAlmostEqual(variants[0].shaft_diameter_mm or 0.0, 12.0, places=3)

    def test_unpowered_reads_middle_step_diameter_from_any_drawing(self) -> None:
        """任一无动力图标了中间直径时，台阶外径跟该图，不写死 15。"""

        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()
        msp.add_mtext(
            "201不锈钢无动力滚筒-臂厚1.5mm",
            dxfattribs={"insert": (0, 0), "char_height": 5},
        )
        msp.add_linear_dim(
            base=(0, 60),
            p1=(0, 0),
            p2=(420, 0),
            dimstyle="EZDXF",
        ).render()
        for text, center in (("%%C76", (40, -30)), ("%%C25", (120, -30)), ("%%C20", (200, -30))):
            dim = msp.add_diameter_dim(
                center=center,
                radius=float(text.replace("%%C", "")) / 2.0,
                angle=40,
                dimstyle="EZDXF",
            )
            dim.dimension.dxf.text = text
            dim.render()
        variants = extract_roller_variants(doc, msp, scale=1.0)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].roller_type, "无动力滚筒")
        self.assertAlmostEqual(variants[0].outer_diameter_mm or 0.0, 76.0, places=3)
        self.assertAlmostEqual(variants[0].shaft_diameter_mm or 0.0, 20.0, places=3)
        self.assertAlmostEqual(variants[0].shaft_step_diameter_mm or 0.0, 25.0, places=3)

    def test_stacked_views_do_not_cross_assign_lengths(self) -> None:
        """同一张图上 700 / 280 / 330 各归各的注记，不会串成全是 700。"""

        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()
        views = (
            (0.0, 1000.0, "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿", 700.0, 13),
            (0.0, 500.0, "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿", 280.0, 1),
            (0.0, 0.0, "201不锈钢无动力滚筒-臂厚1.2mm", 330.0, 1),
        )
        for x, y, note, length, qty in views:
            msp.add_mtext(note, dxfattribs={"insert": (x, y), "char_height": 5})
            msp.add_mtext(
                f"X {qty} 支",
                dxfattribs={"insert": (x + 420, y + 30), "char_height": 5},
            )
            msp.add_linear_dim(
                base=(x, y + 120),
                p1=(x, y + 40),
                p2=(x + length, y + 40),
                dimstyle="EZDXF",
            ).render()
            dim_od = msp.add_diameter_dim(
                center=(x + 80, y - 40),
                radius=25,
                angle=40,
                dimstyle="EZDXF",
            )
            dim_od.dimension.dxf.text = "%%C50"
            dim_od.render()
            dim_shaft = msp.add_diameter_dim(
                center=(x + 200, y - 40),
                radius=6,
                angle=20,
                dimstyle="EZDXF",
            )
            dim_shaft.dimension.dxf.text = "%%C12"
            dim_shaft.render()

        variants = extract_roller_variants(doc, msp, scale=1.0)
        by_length = {
            round(v.overall_length_mm or 0.0): v for v in variants
        }
        self.assertEqual(set(by_length), {700, 280, 330})
        self.assertEqual(by_length[700].quantity, 13)
        self.assertEqual(by_length[700].roller_type, "动力滚筒")
        self.assertEqual(by_length[280].roller_type, "动力滚筒")
        self.assertEqual(by_length[330].roller_type, "无动力滚筒")

    def test_brief_sketch_reads_notes_from_block_definition(self) -> None:
        """布局只有空 INSERT 展开失败时，仍从含滚筒注记的块定义识别。"""

        from unittest.mock import patch

        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        block = doc.blocks.new("ORPHAN_ROLLER")
        block.add_mtext(
            "201不锈钢无动力滚筒-臂厚1.2mm",
            dxfattribs={"insert": (0, 0), "char_height": 5},
        )
        block.add_mtext(
            "X 1 支",
            dxfattribs={"insert": (200, 20), "char_height": 5},
        )
        block.add_linear_dim(
            base=(0, 40),
            p1=(0, 0),
            p2=(330, 0),
            dimstyle="EZDXF",
        ).render()
        # 模型空间不放 INSERT，模拟仅块定义可读。
        with patch(
            "roller_drawing._iter_drawable_entities",
            side_effect=lambda entities, **kwargs: entities,
        ):
            variants = extract_roller_variants(doc, doc.modelspace(), scale=1.0)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].roller_type, "无动力滚筒")
        self.assertAlmostEqual(variants[0].overall_length_mm or 0.0, 330.0, places=3)

    def test_libredwg_fallback_converts_uploaded_sketch_dwg(self) -> None:
        from dwg_converter import (
            DwgConversionError,
            _dwg2dxf_candidates,
            convert_dwg_with_libredwg,
        )

        if not _dwg2dxf_candidates():
            self.skipTest("本机未安装 LibreDWG dwg2dxf")
        source = Path(
            "/home/ubuntu/.cursor/projects/workspace/uploads/"
            "1.3___________________1__3e77.dwg"
        )
        if not source.is_file():
            self.skipTest("未找到上传的斜滚筒草图 DWG")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sketch.dxf"
            try:
                convert_dwg_with_libredwg(source, target)
            except DwgConversionError as error:
                self.skipTest(f"LibreDWG 无法转换此 DWG：{error}")
            named = Path(tmp) / "1.3米斜滚筒线滚筒尺寸图（斜滚筒线专用）(1).dxf"
            named.write_bytes(target.read_bytes())
            analysis = analyze_dxf(named)
        self.assertGreaterEqual(len(analysis.roller_variants), 3)
        by_length = {
            round(v.overall_length_mm or 0.0): v for v in analysis.roller_variants
        }
        self.assertIn(700, by_length)
        self.assertEqual(by_length[700].quantity, 13)
        self.assertAlmostEqual(by_length[700].shaft_diameter_mm or 0.0, 12.0)
        self.assertIn(280, by_length)
        self.assertIn(330, by_length)

    def test_analyze_dxf_routes_roller_notes_across_layouts(self) -> None:
        doc = ezdxf.new()
        doc.units = ezdxf.units.MM
        # 几何在 Model，滚筒注记与尺寸在另一布局——应仍能抽到规格。
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (200, 0), (200, 100), (0, 100)],
            close=True,
            dxfattribs={"layer": "0", "color": 7},
        )
        layout = doc.layouts.new("SW_Model_1")
        layout.add_mtext(
            "201不锈钢动力滚筒-臂厚1.2mm-双排链轮4分14齿",
            dxfattribs={"insert": (0, 0), "char_height": 5},
        )
        layout.add_linear_dim(
            base=(0, 40),
            p1=(0, 0),
            p2=(280, 0),
            dimstyle="EZDXF",
        ).render()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roller_notes.dxf"
            doc.saveas(path)
            analysis = analyze_dxf(path)
        self.assertGreaterEqual(len(analysis.roller_variants), 1)
        self.assertTrue(
            looks_like_roller_drawing(
                analysis.roller_variants,
                bend_count=len(analysis.bend_lines),
                path_name=analysis.path.name,
            )
        )


class ProfileSelectionTests(unittest.TestCase):
    @staticmethod
    def _rect(
        x0: float, y0: float, x1: float, y1: float, *, layer: str = "0"
    ) -> Primitive:
        pts = ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))
        segs = tuple(SketchSegment(a, b) for a, b in zip(pts, pts[1:]))
        return Primitive(pts, True, False, layer, "LWPOLYLINE", segs)

    def test_holes_and_slots_hidden_from_outer_candidates(self) -> None:
        outer = self._rect(0, 0, 100, 50)
        hole = self._rect(20, 15, 40, 35)
        slot = self._rect(60, 20, 90, 30)
        square = self._rect(5, 5, 15, 15)
        profiles = (outer, hole, slot, square)
        self.assertEqual(candidate_profile_indices(profiles), (0,))
        self.assertEqual(set(contained_hole_indices(profiles, 0)), {1, 2, 3})

    def test_inner_detail_in_channel_bbox_not_outer_candidate(self) -> None:
        c_pts = (
            (0.0, 0.0),
            (80.0, 0.0),
            (80.0, 10.0),
            (20.0, 10.0),
            (20.0, 40.0),
            (80.0, 40.0),
            (80.0, 50.0),
            (0.0, 50.0),
            (0.0, 0.0),
        )
        c_outer = Primitive(
            c_pts,
            True,
            False,
            "0",
            "LWPOLYLINE",
            tuple(SketchSegment(a, b) for a, b in zip(c_pts, c_pts[1:])),
        )
        void_square = self._rect(30, 15, 50, 35)
        in_material = self._rect(5, 5, 15, 15)
        profiles = (c_outer, void_square, in_material)
        self.assertEqual(candidate_profile_indices(profiles), (0,))

    def test_click_hits_profile_interior(self) -> None:
        outer = self._rect(0, 0, 100, 40)
        hits, distance = point_hits_profile((50.0, 20.0), outer, edge_tolerance=1.0)
        self.assertTrue(hits)
        self.assertGreater(distance, 1.0)


class ResizeProfileTests(unittest.TestCase):

    def _sample_analysis(self) -> DrawingAnalysis:
        profile = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (0.0, 40.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LWPOLYLINE",
            (
                SketchSegment((0.0, 0.0), (100.0, 0.0)),
                SketchSegment((100.0, 0.0), (100.0, 40.0)),
                SketchSegment((100.0, 40.0), (0.0, 40.0)),
                SketchSegment((0.0, 40.0), (0.0, 0.0)),
            ),
        )
        bend = Primitive(
            ((30.0, 0.0), (30.0, 40.0)),
            False,
            True,
            "折弯线",
            "LINE",
            (SketchSegment((30.0, 0.0), (30.0, 40.0)),),
        )
        hole = Primitive(
            ((10.0, 10.0), (20.0, 10.0), (20.0, 20.0), (10.0, 20.0), (10.0, 10.0)),
            True,
            False,
            "0",
            "LWPOLYLINE",
            (
                SketchSegment((10.0, 10.0), (20.0, 10.0)),
                SketchSegment((20.0, 10.0), (20.0, 20.0)),
                SketchSegment((20.0, 20.0), (10.0, 20.0)),
                SketchSegment((10.0, 20.0), (10.0, 10.0)),
            ),
        )
        # 构成孔的原始线段（与 hole 轮廓不是同一对象），缩短时也要跟着动。
        hole_edge = Primitive(
            ((10.0, 10.0), (20.0, 10.0)),
            False,
            False,
            "0",
            "LINE",
            (SketchSegment((10.0, 10.0), (20.0, 10.0)),),
        )
        return DrawingAnalysis(
            path=Path("sample.dxf"),
            units_name="mm",
            primitives=(profile, bend, hole, hole_edge),
            bend_lines=(bend,),
            profiles=(profile, hole),
            bounds=(0.0, 0.0, 100.0, 40.0),
            layout_name="Model",
        )

    def test_resize_length_keeps_height_and_scales_bend(self) -> None:
        analysis = self._sample_analysis()
        resized = resize_profile_dimensions(analysis, 0, width_mm=150.0)
        min_x, min_y, max_x, max_y = primitive_bounds(resized.profiles[0])
        self.assertAlmostEqual(max_x - min_x, 150.0, places=6)
        self.assertAlmostEqual(max_y - min_y, 40.0, places=6)
        bend = resized.bend_lines[0]
        self.assertAlmostEqual(bend.points[0][0], bend.points[1][0], places=6)
        # 原折弯在 x=30；长度 100→150 后相对中心缩放。
        center_x = 50.0
        expected_x = center_x + (30.0 - center_x) * 1.5
        self.assertAlmostEqual(bend.points[0][0], expected_x, places=6)

    def test_resize_width_only(self) -> None:
        analysis = self._sample_analysis()
        resized = resize_profile_dimensions(analysis, 0, height_mm=60.0)
        min_x, min_y, max_x, max_y = primitive_bounds(resized.profiles[0])
        self.assertAlmostEqual(max_x - min_x, 100.0, places=6)
        self.assertAlmostEqual(max_y - min_y, 60.0, places=6)

    def test_resize_syncs_hole_and_source_line(self) -> None:
        analysis = self._sample_analysis()
        resized = resize_profile_dimensions(analysis, 0, width_mm=50.0)
        hole = resized.profiles[1]
        min_x, min_y, max_x, max_y = primitive_bounds(hole)
        # 孔随长度 100→50（中心 50）缩放：原 x=10..20 → 30..35。
        self.assertAlmostEqual(min_x, 30.0, places=6)
        self.assertAlmostEqual(max_x, 35.0, places=6)
        self.assertAlmostEqual(min_y, 10.0, places=6)
        self.assertAlmostEqual(max_y, 20.0, places=6)
        edge = resized.primitives[3]
        self.assertAlmostEqual(edge.points[0][0], 30.0, places=6)
        self.assertAlmostEqual(edge.points[1][0], 35.0, places=6)

    def test_shorten_keeps_single_arc_fillets(self) -> None:
        """单向缩短后圆角仍是单段真圆弧，不能密化成多段折线。"""

        from profile_sanitize import contour_self_intersects

        center = (90.0, 20.0)
        # 带圆弧的长槽：直线 + 半圆弧端头。
        points = (
            (0.0, 0.0),
            (80.0, 0.0),
            (100.0, 20.0),
            (80.0, 40.0),
            (0.0, 40.0),
            (0.0, 0.0),
        )
        curves = (
            SketchSegment((0.0, 0.0), (80.0, 0.0)),
            SketchSegment(
                (80.0, 0.0),
                (80.0, 40.0),
                center,
                math.pi,
            ),
            SketchSegment((80.0, 40.0), (0.0, 40.0)),
            SketchSegment((0.0, 40.0), (0.0, 0.0)),
        )
        profile = Primitive(points, True, False, "0", "LINE_LOOP", curves)
        analysis = DrawingAnalysis(
            path=Path("slot.dxf"),
            units_name="mm",
            primitives=(profile,),
            bend_lines=(),
            profiles=(profile,),
            bounds=(0.0, 0.0, 100.0, 40.0),
            layout_name="Model",
        )
        resized = resize_profile_dimensions(analysis, 0, width_mm=70.0)
        result = resized.profiles[0]
        self.assertTrue(result.closed)
        arcs = [
            segment
            for segment in result.curve_segments
            if segment.center is not None and abs(segment.sweep_angle) > 1e-8
        ]
        self.assertEqual(len(arcs), 1, "圆角必须仍是恰好一段圆弧")
        self.assertFalse(contour_self_intersects(result.points))
        # 用离散包围盒核对目标长度（与缩短算法一致）。
        from profile_sanitize import densify_closed_profile

        densified = densify_closed_profile(result)
        min_x, _min_y, max_x, _max_y = primitive_bounds(densified)
        self.assertAlmostEqual(max_x - min_x, 70.0, places=2)

    def test_refit_polyline_fillets_to_single_arcs(self) -> None:
        """密化折线圆角应重拟成单段真圆弧，供 SolidWorks CreateArc。"""

        from profile_sanitize import densify_closed_profile, refit_circular_fillets

        radius = 5.0
        # 带四个 R5 圆角的矩形（真弧）。
        corner_defs = (
            ((0.0, 5.0), (5.0, 0.0), (5.0, 5.0), -math.pi / 2),
            ((35.0, 0.0), (40.0, 5.0), (35.0, 5.0), -math.pi / 2),
            ((40.0, 35.0), (35.0, 40.0), (35.0, 35.0), -math.pi / 2),
            ((5.0, 40.0), (0.0, 35.0), (5.0, 35.0), -math.pi / 2),
        )
        curves = (
            SketchSegment(corner_defs[0][0], corner_defs[0][1], corner_defs[0][2], corner_defs[0][3]),
            SketchSegment(corner_defs[0][1], corner_defs[1][0]),
            SketchSegment(corner_defs[1][0], corner_defs[1][1], corner_defs[1][2], corner_defs[1][3]),
            SketchSegment(corner_defs[1][1], corner_defs[2][0]),
            SketchSegment(corner_defs[2][0], corner_defs[2][1], corner_defs[2][2], corner_defs[2][3]),
            SketchSegment(corner_defs[2][1], corner_defs[3][0]),
            SketchSegment(corner_defs[3][0], corner_defs[3][1], corner_defs[3][2], corner_defs[3][3]),
            SketchSegment(corner_defs[3][1], corner_defs[0][0]),
        )
        points = (
            corner_defs[0][0],
            corner_defs[0][1],
            corner_defs[1][0],
            corner_defs[1][1],
            corner_defs[2][0],
            corner_defs[2][1],
            corner_defs[3][0],
            corner_defs[3][1],
            corner_defs[0][0],
        )
        profile = Primitive(points, True, False, "0", "LINE_LOOP", curves)
        densified = densify_closed_profile(profile, segments_per_arc=12)
        self.assertFalse(
            any(
                segment.center is not None and abs(segment.sweep_angle) > 1e-8
                for segment in densified.curve_segments
            )
        )
        refit = refit_circular_fillets(densified)
        arcs = [
            segment
            for segment in refit.curve_segments
            if segment.center is not None and abs(segment.sweep_angle) > 1e-8
        ]
        self.assertEqual(len(arcs), 4, "四个折线圆角应各重拟成一段圆弧")
        for arc in arcs:
            self.assertAlmostEqual(
                math.hypot(arc.start[0] - arc.center[0], arc.start[1] - arc.center[1]),
                radius,
                places=1,
            )

    def test_shorten_polyline_fillets_become_single_arcs(self) -> None:
        """CAD 折线圆角在缩短后也要变成单段弧，不能仍是多线段。"""

        from profile_sanitize import densify_closed_profile

        corner_defs = (
            ((0.0, 5.0), (5.0, 0.0), (5.0, 5.0), -math.pi / 2),
            ((95.0, 0.0), (100.0, 5.0), (95.0, 5.0), -math.pi / 2),
            ((100.0, 35.0), (95.0, 40.0), (95.0, 35.0), -math.pi / 2),
            ((5.0, 40.0), (0.0, 35.0), (5.0, 35.0), -math.pi / 2),
        )
        curves = (
            SketchSegment(corner_defs[0][0], corner_defs[0][1], corner_defs[0][2], corner_defs[0][3]),
            SketchSegment(corner_defs[0][1], corner_defs[1][0]),
            SketchSegment(corner_defs[1][0], corner_defs[1][1], corner_defs[1][2], corner_defs[1][3]),
            SketchSegment(corner_defs[1][1], corner_defs[2][0]),
            SketchSegment(corner_defs[2][0], corner_defs[2][1], corner_defs[2][2], corner_defs[2][3]),
            SketchSegment(corner_defs[2][1], corner_defs[3][0]),
            SketchSegment(corner_defs[3][0], corner_defs[3][1], corner_defs[3][2], corner_defs[3][3]),
            SketchSegment(corner_defs[3][1], corner_defs[0][0]),
        )
        points = (
            corner_defs[0][0],
            corner_defs[0][1],
            corner_defs[1][0],
            corner_defs[1][1],
            corner_defs[2][0],
            corner_defs[2][1],
            corner_defs[3][0],
            corner_defs[3][1],
            corner_defs[0][0],
        )
        true_arc = Primitive(points, True, False, "0", "LINE_LOOP", curves)
        polyline = densify_closed_profile(true_arc, segments_per_arc=10)
        analysis = DrawingAnalysis(
            path=Path("poly-fillet.dxf"),
            units_name="mm",
            primitives=(polyline,),
            bend_lines=(),
            profiles=(polyline,),
            bounds=(0.0, 0.0, 100.0, 40.0),
            layout_name="Model",
        )
        resized = resize_profile_dimensions(analysis, 0, width_mm=70.0)
        result = resized.profiles[0]
        arcs = [
            segment
            for segment in result.curve_segments
            if segment.center is not None and abs(segment.sweep_angle) > 1e-8
        ]
        self.assertGreaterEqual(len(arcs), 4, "缩短后折线圆角必须重拟成圆弧")
        line_count = sum(
            1
            for segment in result.curve_segments
            if segment.center is None or abs(segment.sweep_angle) <= 1e-8
        )
        self.assertLess(
            line_count,
            len(polyline.curve_segments) // 2,
            "不能仍保留密化多线段",
        )

    def test_generator_imports_refit_for_create_arc(self) -> None:
        """基体草图路径必须能导入并调用圆角重拟（避免再强制折线）。"""

        import solidworks_generator as sw

        self.assertTrue(hasattr(sw, "refit_circular_fillets"))
        source = Path(sw.__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("curve_segments=attempt_profile.curve_segments", source)
        self.assertIn("refit_circular_fillets(profile)", source)
        self.assertIn("_polyline_only_profile(", source)
        self.assertNotIn(
            "curve_segments=(),\n                circle_center=None",
            source,
        )

    def test_bend_position_is_centerline(self) -> None:
        """折弯位置必须是折弯中心线（草图折弯枚举值 1，不是边法兰的 4）。"""

        import solidworks_generator as sw

        self.assertEqual(sw.SW_BEND_POSITION_BEND_CENTERLINE, 1)
        self.assertEqual(sw.SW_BEND_POSITION_BEND_OUTSIDE, 4)
        source = Path(sw.__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("SW_BEND_POSITION_BEND_CENTERLINE,", source)
        self.assertIn(
            "不要用边法兰 swFlangePositionTypeBendCenterLine=4",
            source,
        )

    def test_auto_bend_uses_all_in_one_sketch_fallback(self) -> None:
        """自动折弯必须先同草图一次折，而不是默认逐条（首折后钣金已非平面）。"""

        import solidworks_generator as sw

        source = Path(sw.__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("_create_bends_with_fallbacks(", source)
        self.assertIn("先全部同草图", source)
        # 调用点应把全部 selected_bends 交给调度，而不是 for 循环逐条 _create_bend_feature。
        self.assertNotIn(
            "for bend_index in selected_bends:\n                _create_bend_feature(",
            source,
        )

    def test_base_extrude_fallback_uses_merge_false(self) -> None:
        """空零件首次拉伸必须 Merge=False，否则多版本 FeatureExtrusion2 直接失败。"""

        import solidworks_generator as sw

        source = Path(sw.__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn("def _try_extrude_thin_solid(", source)
        self.assertIn("(False, False, True, False)", source)
        self.assertIn("_select_sketch_contours(", source)
        self.assertIn("_polyline_only_profile(", source)

    def test_polyline_only_profile_strips_arcs(self) -> None:
        from cad_analyzer import SketchSegment
        from solidworks_generator import _polyline_only_profile

        arc = SketchSegment(
            (100.0, 0.0),
            (100.0, 50.0),
            center=(100.0, 25.0),
            sweep_angle=math.pi,
        )
        profile = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
            (
                SketchSegment((0.0, 0.0), (100.0, 0.0)),
                arc,
                SketchSegment((100.0, 50.0), (0.0, 50.0)),
                SketchSegment((0.0, 50.0), (0.0, 0.0)),
            ),
        )
        plain = _polyline_only_profile(profile)
        self.assertEqual(plain.kind, "LINE_LOOP")
        self.assertTrue(all(segment.center is None for segment in plain.curve_segments))
        self.assertGreaterEqual(len(plain.curve_segments), 3)

    def test_fixed_face_candidates_prefer_middle_strip(self) -> None:
        """U 型双折弯时，固定面候选应包含中间底板区域。"""

        from solidworks_generator import _fixed_face_pick_candidates

        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (0.0, 40.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        bend_a = Primitive(((20.0, 0.0), (20.0, 40.0)), False, True, "折弯线", "LINE")
        bend_b = Primitive(((80.0, 0.0), (80.0, 40.0)), False, True, "折弯线", "LINE")
        candidates = _fixed_face_pick_candidates(outer, (bend_a, bend_b))
        self.assertGreaterEqual(len(candidates), 3)
        # 至少有一个点落在两条折弯之间（中间不动区）。
        self.assertTrue(
            any(20.0 < point[0] < 80.0 for point in candidates),
            candidates,
        )
        # 候选不应压在折弯线上。
        for point in candidates:
            self.assertGreater(abs(point[0] - 20.0), 0.1)
            self.assertGreater(abs(point[0] - 80.0), 0.1)

    def test_partition_parallel_and_crossing_bends(self) -> None:
        from solidworks_generator import _partition_bend_groups

        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        parallel_a = Primitive(((25.0, 5.0), (25.0, 75.0)), False, True, "折弯线", "LINE")
        parallel_b = Primitive(((75.0, 5.0), (75.0, 75.0)), False, True, "折弯线", "LINE")
        crossing = Primitive(((5.0, 40.0), (95.0, 40.0)), False, True, "折弯线", "LINE")
        analysis = DrawingAnalysis(
            path=Path("cross-bend.dxf"),
            units_name="mm",
            primitives=(outer, parallel_a, parallel_b, crossing),
            bend_lines=(parallel_a, parallel_b, crossing),
            profiles=(outer,),
            bounds=(0.0, 0.0, 100.0, 80.0),
            layout_name="Model",
        )
        groups = _partition_bend_groups(analysis, (0, 1, 2))
        self.assertEqual(len(groups), 2)
        self.assertEqual(set(groups[0]), {0, 1})
        self.assertEqual(groups[1], (2,))

    def test_bend_segment_keeps_drawn_length(self) -> None:
        from solidworks_generator import _extended_bend_segment

        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (0.0, 40.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        bend = Primitive(((30.0, 5.0), (30.0, 35.0)), False, True, "折弯线", "LINE")
        start, end = _extended_bend_segment(bend, outer, thickness_mm=1.5)
        self.assertEqual(start, (30.0, 5.0))
        self.assertEqual(end, (30.0, 35.0))
        self.assertAlmostEqual(math.dist(start, end), 30.0)

    def test_feature_bend_crosses_outline_without_stretching_recognition(self) -> None:
        """特征草图要穿出板边，但只探出约 1mm，识别线段本身不变。"""

        from solidworks_generator import (
            BEND_FEATURE_PIERCE_MM,
            _bend_feature_segment,
            _extended_bend_segment,
        )

        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (0.0, 40.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        bend = Primitive(((30.0, 8.0), (30.0, 28.0)), False, True, "折弯线", "LINE")
        drawn = _extended_bend_segment(bend, outer, thickness_mm=2.5)
        self.assertEqual(drawn, ((30.0, 8.0), (30.0, 28.0)))
        start, end = _bend_feature_segment(bend, outer, thickness_mm=2.5)
        self.assertAlmostEqual(start[0], 30.0)
        self.assertAlmostEqual(end[0], 30.0)
        self.assertLess(start[1], 0.0)
        self.assertGreater(end[1], 40.0)
        self.assertAlmostEqual(0.0 - start[1], BEND_FEATURE_PIERCE_MM, places=3)
        self.assertAlmostEqual(end[1] - 40.0, BEND_FEATURE_PIERCE_MM, places=3)
        self.assertLess(end[1] - start[1], 50.0)

    def test_feature_line_spans_part_when_mark_only_nicks_one_edge(self) -> None:
        """只碰到一条边的红线，特征草图仍要穿过整块板。识别端点不变。"""

        from solidworks_generator import _bend_feature_segment, _extended_bend_segment

        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (0.0, 40.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        bend = Primitive(((30.0, -5.0), (30.0, 10.0)), False, True, "折弯线", "LINE")
        self.assertEqual(
            _extended_bend_segment(bend, outer, thickness_mm=2.5),
            ((30.0, -5.0), (30.0, 10.0)),
        )
        start, end = _bend_feature_segment(bend, outer, thickness_mm=2.5)
        self.assertLess(min(start[1], end[1]), 0.0)
        self.assertGreater(max(start[1], end[1]), 40.0)

    def test_two_collinear_bends_collapse_to_one_feature_line(self) -> None:
        """共线的两条折弯线只进一次折弯，避免 SolidWorks 报错。识别仍是两条。"""

        from solidworks_generator import collapse_collinear_bend_indices

        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (0.0, 40.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        first = Primitive(((10.0, 20.0), (30.0, 20.0)), False, True, "折弯线", "LINE")
        second = Primitive(((70.0, 20.0), (90.0, 20.0)), False, True, "折弯线", "LINE")
        offset = Primitive(((10.0, 30.0), (90.0, 30.0)), False, True, "折弯线", "LINE")
        analysis = DrawingAnalysis(
            path=Path("collinear-bends.dxf"),
            units_name="mm",
            primitives=(outer, first, second, offset),
            bend_lines=(first, second, offset),
            profiles=(outer,),
            bounds=(0.0, 0.0, 100.0, 40.0),
            layout_name="Model",
        )
        self.assertEqual(collapse_collinear_bend_indices(analysis, (0, 1, 2)), (0, 2))
        self.assertEqual(len(analysis.bend_lines), 3)

    def test_shorten_keeps_bend_lines_crossing_profile(self) -> None:
        """改长度后折弯线仍应穿过轮廓——自动折弯失败通常不是缩短把线弄断。"""

        from solidworks_generator import _bend_outline_ends, _point_in_profile

        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 40.0), (0.0, 40.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        bend_a = Primitive(((20.0, 5.0), (20.0, 35.0)), False, True, "折弯线", "LINE")
        bend_b = Primitive(((80.0, 5.0), (80.0, 35.0)), False, True, "折弯线", "LINE")
        analysis = DrawingAnalysis(
            path=Path("shorten-bend.dxf"),
            units_name="mm",
            primitives=(outer, bend_a, bend_b),
            bend_lines=(bend_a, bend_b),
            profiles=(outer,),
            bounds=(0.0, 0.0, 100.0, 40.0),
            layout_name="Model",
        )
        resized = resize_profile_dimensions(analysis, 0, width_mm=70.0)
        profile = resized.profiles[0]
        for bend in resized.bend_lines:
            mid = (
                (bend.points[0][0] + bend.points[-1][0]) / 2.0,
                (bend.points[0][1] + bend.points[-1][1]) / 2.0,
            )
            self.assertTrue(_point_in_profile(mid, profile))
            self.assertGreaterEqual(len(_bend_outline_ends(bend, profile)), 1)

    def test_resize_rejects_non_positive(self) -> None:
        analysis = self._sample_analysis()
        with self.assertRaises(ValueError):
            resize_profile_dimensions(analysis, 0, width_mm=0.0)


if __name__ == "__main__":
    unittest.main()
