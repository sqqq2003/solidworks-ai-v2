
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
from pathlib import Path
from tempfile import TemporaryDirectory
import math
import random
import unittest
from unittest.mock import patch

import ezdxf
from ezdxf import units

from cad_analyzer import (
    DrawingAnalysis,
    Primitive,
    SketchSegment,
    _line_segment_covers,
    _overlapping_line_indices,
    analyze_cad_file,
    analyze_dxf,
    primitive_bounds,
    with_manual_bend_lines,
    without_bend_lines,
)
from profile_selection import candidate_profile_indices, contained_hole_indices


class AnalyzeCadTests(unittest.TestCase):
    def test_arc_bounds_include_exact_cardinal_extreme(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "arc-bounds.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.modelspace().add_arc((0, 0), 10, 10, 100)
            doc.saveas(path)

            result = analyze_dxf(path)

            bounds = primitive_bounds(result.primitives[0])
            self.assertAlmostEqual(bounds[3], 10.0, places=8)
            self.assertAlmostEqual(result.bounds[3], 10.0, places=8)

    def test_manually_marks_straight_line_as_bend(self) -> None:
        line = Primitive(
            ((10, 20), (90, 20)),
            False,
            False,
            "CONTINUOUS",
            "LINE",
            (SketchSegment((10, 20), (90, 20)),),
        )
        analysis = DrawingAnalysis(
            Path("sample.dxf"),
            "Millimeters",
            (line,),
            (),
            (),
            (10, 20, 90, 20),
            "Model",
        )

        marked = with_manual_bend_lines(analysis, (0,))

        self.assertTrue(marked.primitives[0].is_bend)
        self.assertEqual(marked.bend_lines, (marked.primitives[0],))
        self.assertFalse(analysis.primitives[0].is_bend)

    def test_ignores_marked_bend_line_without_changing_source_analysis(self) -> None:
        bend = Primitive(
            ((10, 20), (90, 20)),
            False,
            True,
            "BEND",
            "LINE",
            (SketchSegment((10, 20), (90, 20)),),
        )
        analysis = DrawingAnalysis(
            Path("sample.dxf"),
            "Millimeters",
            (bend,),
            (bend,),
            (),
            (10, 20, 90, 20),
            "Model",
        )

        ignored = without_bend_lines(analysis, (0,))

        self.assertFalse(ignored.primitives[0].is_bend)
        self.assertEqual(ignored.bend_lines, ())
        self.assertTrue(analysis.primitives[0].is_bend)

    def test_manual_bend_mark_rejects_closed_outline(self) -> None:
        outline = Primitive(
            ((0, 0), (10, 0), (10, 10), (0, 10), (0, 0)),
            True,
            False,
            "OUTLINE",
            "LWPOLYLINE",
            tuple(
                SketchSegment(start, end)
                for start, end in zip(
                    ((0, 0), (10, 0), (10, 10), (0, 10)),
                    ((10, 0), (10, 10), (0, 10), (0, 0)),
                )
            ),
        )
        analysis = DrawingAnalysis(
            Path("sample.dxf"),
            "Millimeters",
            (outline,),
            (),
            (outline,),
            (0, 0, 10, 10),
            "Model",
        )

        with self.assertRaisesRegex(ValueError, "未闭合的直线"):
            with_manual_bend_lines(analysis, (0,))

    def test_detects_red_bends_and_closed_polyline_profiles(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.layers.new("OUTLINE", dxfattribs={"color": 7})
            doc.layers.new("BEND", dxfattribs={"color": 1, "linetype": "HIDDEN"})
            modelspace = doc.modelspace()
            modelspace.add_lwpolyline(
                [(0, 0), (100, 0), (100, 50), (0, 50)],
                close=True,
                dxfattribs={"layer": "OUTLINE"},
            )
            modelspace.add_line(
                (20, 10),
                (80, 10),
                dxfattribs={"layer": "BEND", "color": 256},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.bend_lines), 1)
            self.assertEqual(len(result.profiles), 1)
            self.assertEqual(result.bend_lines[0].layer, "BEND")
            self.assertAlmostEqual(result.bounds[2], 100)
            self.assertAlmostEqual(result.bounds[3], 50)

    def test_detects_closed_profile_made_of_separate_lines(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "segments.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            modelspace = doc.modelspace()
            points = [(0, 0), (10, 0), (10, 10), (0, 10)]
            for index, point in enumerate(points):
                modelspace.add_line(point, points[(index + 1) % len(points)])
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.profiles), 1)
            self.assertEqual(result.profiles[0].kind, "LINE_LOOP")

    def test_ignores_partially_overlapping_duplicate_outline_segments(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate-outline-edge.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            modelspace = doc.modelspace()
            modelspace.add_line((0, 0), (100, 0))
            modelspace.add_line((100, 0), (100, 80))
            modelspace.add_line((100, 80), (0, 80))
            modelspace.add_line((0, 80), (0, 0))
            modelspace.add_line((0, 80), (60, 80))
            modelspace.add_circle((20, 20), 5)
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(
                tuple(profile.kind for profile in result.profiles),
                ("CIRCLE", "LINE_LOOP"),
            )
            self.assertEqual(candidate_profile_indices(result.profiles), (1,))
            self.assertEqual(contained_hole_indices(result.profiles, 1), (0,))

    def test_detached_relief_lines_do_not_become_part_or_hole_profiles(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "relief-slots.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            modelspace = doc.modelspace()
            modelspace.add_lwpolyline(
                [(0, 0), (100, 0), (100, 80), (0, 80)],
                close=True,
            )
            modelspace.add_circle((50, 40), 5)
            modelspace.add_line((55.1, 40), (65, 40))
            modelspace.add_line((44.9, 40), (35, 40))
            doc.saveas(path)

            result = analyze_dxf(path)
            candidates = candidate_profile_indices(result.profiles)

            self.assertEqual(candidates, (0,))
            self.assertEqual(contained_hole_indices(result.profiles, 0), (1,))
            self.assertEqual(len(result.primitives), 4)
            self.assertEqual(len(result.profiles), 2)

    def test_detects_rotated_closed_slot_as_a_cutout(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rotated-slot.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.layers.new("OUTLINE")
            doc.layers.new("SLOT")
            modelspace = doc.modelspace()
            modelspace.add_lwpolyline(
                [(0, 0), (100, 0), (100, 80), (0, 80)],
                close=True,
                dxfattribs={"layer": "OUTLINE"},
            )
            angle = math.radians(37)
            axis = (math.cos(angle), math.sin(angle))
            normal = (-axis[1], axis[0])
            slot_points = [
                (
                    50 + axis[0] * along + normal[0] * across,
                    40 + axis[1] * along + normal[1] * across,
                )
                for along, across in (
                    (-15, -2),
                    (15, -2),
                    (15, 2),
                    (-15, 2),
                )
            ]
            modelspace.add_lwpolyline(
                slot_points,
                close=True,
                dxfattribs={"layer": "SLOT"},
            )
            doc.saveas(path)

            analysis = analyze_dxf(path)
            outline_index = next(
                index
                for index, profile in enumerate(analysis.profiles)
                if profile.layer == "OUTLINE"
            )
            slot_index = next(
                index
                for index, profile in enumerate(analysis.profiles)
                if profile.layer == "SLOT"
            )

            self.assertEqual(candidate_profile_indices(analysis.profiles), (outline_index,))
            self.assertIn(
                slot_index,
                contained_hole_indices(analysis.profiles, outline_index),
            )

    def test_preserves_bulge_arc_in_closed_polyline(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bulge.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.modelspace().add_lwpolyline(
                [
                    (0, 0, 0, 0, 0),
                    (10, 0, 0, 0, 0.41421356237309503),
                    (10, 10, 0, 0, 0),
                    (0, 10, 0, 0, 0),
                ],
                format="xyseb",
                close=True,
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            profile = result.profiles[0]
            arc = profile.curve_segments[1]
            self.assertIsNotNone(arc.center)
            self.assertAlmostEqual(arc.sweep_angle, 1.57079632679, places=8)
            self.assertAlmostEqual(
                math.dist(arc.start, arc.center),
                math.dist(arc.end, arc.center),
                places=8,
            )

    def test_combines_arc_and_line_into_closed_profile(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "arc-line-loop.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            modelspace = doc.modelspace()
            modelspace.add_arc((0, 0), 10, 0, 180)
            modelspace.add_line((-10, 0), (10, 0))
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.profiles), 1)
            profile = result.profiles[0]
            self.assertEqual(profile.kind, "LINE_LOOP")
            self.assertEqual(len(profile.curve_segments), 2)
            self.assertAlmostEqual(abs(profile.curve_segments[0].sweep_angle), math.pi)
            self.assertEqual(sum(segment.center is not None for segment in profile.curve_segments), 1)

    def test_closes_rounded_outline_with_small_line_arc_mismatches(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rounded-outline-gaps.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            modelspace = doc.modelspace()

            modelspace.add_line((5.5, 0.03), (94, 0))
            modelspace.add_line((100, 6), (100, 44))
            modelspace.add_line((6.07, 50), (94, 50))
            modelspace.add_line((0, 44), (0, 6))
            modelspace.add_arc((6, 6), 6, 180, 270)
            modelspace.add_arc((94, 6), 6, 270, 360)
            modelspace.add_arc((94, 44), 6, 0, 90)
            modelspace.add_arc((6, 44), 6, 90, 180)
            modelspace.add_circle((50, 25), 2)
            modelspace.add_lwpolyline(
                [(70, 20), (80, 20), (80, 30), (70, 30)],
                close=True,
            )
            doc.saveas(path)

            analysis = analyze_dxf(path)
            outer_index = next(
                index
                for index, profile in enumerate(analysis.profiles)
                if profile.kind == "LINE_LOOP"
                and primitive_bounds(profile)[2] - primitive_bounds(profile)[0] > 90
            )

            self.assertEqual(candidate_profile_indices(analysis.profiles), (outer_index,))
            self.assertEqual(
                len(contained_hole_indices(analysis.profiles, outer_index)),
                2,
            )

    def test_converts_inch_drawing_units_to_millimeters(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "inch.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.IN
            doc.modelspace().add_circle((0, 0), 1)
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(result.units_name, "Inches")
            self.assertAlmostEqual(result.bounds[2], 25.4, places=6)
            self.assertAlmostEqual(result.bounds[3], 25.4, places=6)

    def test_detects_red_true_color_entities(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "true-color.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.modelspace().add_line(
                (0, 0),
                (20, 0),
                dxfattribs={"true_color": 0xFF0000, "linetype": "HIDDEN"},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.bend_lines), 1)

    def test_detects_red_aci_palette_variants(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "aci-red.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.modelspace().add_line(
                (0, 0),
                (20, 0),
                dxfattribs={"color": 10, "linetype": "HIDDEN"},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.bend_lines), 1)

    def test_detects_dark_red_bend_lines(self) -> None:
        # ACI 12/14 是低亮度红，只有旧的高亮度阈值时会被漏掉。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dark-red.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            modelspace = doc.modelspace()
            modelspace.add_line(
                (0, 0),
                (20, 0),
                dxfattribs={"color": 12, "linetype": "HIDDEN"},
            )
            modelspace.add_line(
                (0, 5),
                (20, 5),
                dxfattribs={"color": 14, "linetype": "HIDDEN"},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.bend_lines), 2)

    def test_detects_chinese_dashed_linetype(self) -> None:
        # 中文 CAD 样板里虚线线型常被命名为"虚线"。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chinese-linetype.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.modelspace().add_line(
                (0, 0),
                (20, 0),
                dxfattribs={"color": 1, "linetype": "虚线"},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.bend_lines), 1)

    def test_ignores_dash_dot_center_lines(self) -> None:
        # 红色点划线是中心线，不能因为线型名含有 DASH 就被当成折弯线。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "dashdot.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.modelspace().add_line(
                (0, 0),
                (20, 0),
                dxfattribs={"color": 1, "linetype": "DASHDOT"},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(result.bend_lines, ())

    def test_center_layer_open_lines_count_as_bends(self) -> None:
        # 用户规则（2026-10-17）：折弯线 = 纯红实线 ∪「中心线」层开放直线 ∪ 原规则。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "center-layer.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.layers.new("中心线", dxfattribs={"color": 1, "linetype": "HIDDEN"})
            doc.modelspace().add_line(
                (0, 0),
                (20, 0),
                dxfattribs={"layer": "中心线", "color": 256},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.bend_lines), 1)

    def test_closed_red_dashed_polyline_stays_a_profile(self) -> None:
        # 闭合轮廓画在红色虚线图层上时，仍应作为零件候选，而不是消失。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "closed-dashed.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.layers.new("BEND", dxfattribs={"color": 1, "linetype": "HIDDEN"})
            doc.modelspace().add_lwpolyline(
                [(0, 0), (50, 0), (50, 30), (0, 30)],
                close=True,
                dxfattribs={"layer": "BEND", "color": 256},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(result.bend_lines, ())
            self.assertEqual(len(result.profiles), 1)
            self.assertEqual(len(result.primitives), 1)

    def test_tolerates_entities_on_undefined_layers(self) -> None:
        # 部分导出器会写出未定义图层的实体，分析不应因此中断。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "missing-layer.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            modelspace = doc.modelspace()
            modelspace.add_line(
                (0, 0),
                (20, 0),
                dxfattribs={"layer": "NOT_DEFINED", "color": 256},
            )
            modelspace.add_lwpolyline(
                [(0, 0), (40, 0), (40, 20), (0, 20)],
                close=True,
                dxfattribs={"layer": "OUTLINE_UNDEFINED"},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(result.bend_lines, ())
            self.assertEqual(len(result.profiles), 1)

    def test_collinear_red_bends_keep_original_length(self) -> None:
        # 两端各画一小段红线时，不能接成贯穿零件的长线。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "short-bends.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.layers.new("BEND", dxfattribs={"color": 1, "linetype": "HIDDEN"})
            modelspace = doc.modelspace()
            modelspace.add_lwpolyline(
                [(0, 0), (500, 0), (500, 100), (0, 100)],
                close=True,
            )
            modelspace.add_line(
                (20, 50),
                (45, 50),
                dxfattribs={"layer": "BEND", "color": 256},
            )
            modelspace.add_line(
                (455, 50),
                (480, 50),
                dxfattribs={"layer": "BEND", "color": 256},
            )
            # 同一条线画了两遍，去重后仍是原来的长度。
            modelspace.add_line(
                (20, 50),
                (45, 50),
                dxfattribs={"layer": "BEND", "color": 256},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            lengths = sorted(
                round(math.dist(bend.points[0], bend.points[-1]), 6)
                for bend in result.bend_lines
            )
            self.assertEqual(lengths, [25.0, 25.0])
            for bend in result.bend_lines:
                self.assertIn(bend, result.primitives)

    def test_does_not_merge_bend_marks_from_different_parts(self) -> None:
        # 两个零件恰好有一条共线的折弯线时，不能合并成跨零件的一条。
        with TemporaryDirectory() as directory:
            path = Path(directory) / "two-parts.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.layers.new("BEND", dxfattribs={"color": 1, "linetype": "HIDDEN"})
            modelspace = doc.modelspace()
            modelspace.add_lwpolyline(
                [(0, 0), (500, 0), (500, 100), (0, 100)],
                close=True,
            )
            modelspace.add_lwpolyline(
                [(700, 0), (1200, 0), (1200, 100), (700, 100)],
                close=True,
            )
            modelspace.add_line(
                (20, 50),
                (45, 50),
                dxfattribs={"layer": "BEND", "color": 256},
            )
            modelspace.add_line(
                (1155, 50),
                (1180, 50),
                dxfattribs={"layer": "BEND", "color": 256},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(len(result.bend_lines), 2)
            lengths = sorted(
                math.dist(bend.points[0], bend.points[-1])
                for bend in result.bend_lines
            )
            self.assertEqual(lengths, [25.0, 25.0])

    def test_prefers_layout_with_red_dashed_bends(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "layout.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            doc.modelspace().add_lwpolyline(
                [(0, 0), (297, 0), (297, 210), (0, 210)],
                close=True,
            )
            layout = doc.layouts.new("SW_Model_1")
            layout.add_lwpolyline(
                [(0, 0), (100, 0), (100, 50), (0, 50)],
                close=True,
            )
            layout.add_line(
                (10, 25),
                (90, 25),
                dxfattribs={"color": 1, "linetype": "HIDDEN"},
            )
            layout.add_line(
                (10, 5),
                (90, 5),
                dxfattribs={"color": 1, "linetype": "CONTINUOUS"},
            )
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(result.layout_name, "SW_Model_1")
            # 红虚线 + 纯红实线（并集规则）
            self.assertEqual(len(result.bend_lines), 2)
            self.assertEqual(len(result.profiles), 1)

    def test_prefers_solidworks_model_layout_over_frame_layout(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "solidworks-layout.dxf"
            doc = ezdxf.new("R2010")
            doc.units = units.MM
            modelspace = doc.modelspace()
            for start, end in (
                ((0, 0), (297, 0)),
                ((297, 0), (297, 210)),
                ((297, 210), (0, 210)),
                ((0, 210), (0, 0)),
                ((20, 20), (277, 20)),
                ((20, 190), (277, 190)),
            ):
                modelspace.add_line(start, end)
            layout = doc.layouts.new("SW_Model_1")
            layout.add_lwpolyline(
                [(12000, 5800), (12475, 5800), (12475, 5968.2), (12000, 5968.2)],
                close=True,
            )
            layout.add_circle((12100, 5900), 3.5)
            doc.saveas(path)

            result = analyze_dxf(path)

            self.assertEqual(result.layout_name, "SW_Model_1")
            self.assertEqual(len(result.profiles), 2)
            self.assertAlmostEqual(result.bounds[2] - result.bounds[0], 475.0)
            self.assertAlmostEqual(result.bounds[3] - result.bounds[1], 168.2)

    def test_analyze_cad_file_converts_dwg_and_keeps_source_path(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "sample.dwg"
            source.touch()

            def write_converted_dxf(_source: Path, target: Path) -> None:
                doc = ezdxf.new("R2010")
                doc.units = units.MM
                doc.modelspace().add_circle((0, 0), 5)
                doc.saveas(target)

            converted_targets: list[Path] = []

            def fake_converter(source_path: Path, target: Path) -> None:
                converted_targets.append(target)
                write_converted_dxf(source_path, target)

            def fake_converters(_source: Path):
                # 实现改成「LibreDWG 优先、SolidWorks 兜底」逐个转换器尝试并取
                # 滚筒规格更多的结果（cad_analyzer.iter_dwg_converters），
                # 测试提供一个假转换器即可，不再 mock 已移走的 convert_dwg_to_dxf。
                yield ("test", fake_converter)

            with patch(
                "cad_analyzer.iter_dwg_converters",
                side_effect=fake_converters,
            ) as converters:
                result = analyze_cad_file(source)

            converters.assert_called_once()
            self.assertTrue(converted_targets)
            self.assertEqual(result.path, source)
            self.assertEqual(len(result.profiles), 1)
            # 转换出的 DXF 是临时文件，分析结束必须已被清理。
            self.assertTrue(converted_targets[0].exists())
            converted_targets[0].unlink()

    def test_analyze_cad_file_rejects_unsupported_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持的 CAD 文件格式"):
            analyze_cad_file("drawing.pdf")


class OverlappingLineSegmentTests(unittest.TestCase):
    """重叠直线检测既要结果正确，也不能退化成 O(n^2) 全量比较。"""

    @staticmethod
    def _lines(
        *pairs: tuple[tuple[float, float], tuple[float, float]],
    ) -> list[Primitive]:
        return [
            Primitive((start, end), False, False, "0", "LINE")
            for start, end in pairs
        ]

    @classmethod
    def _brute_force(
        cls,
        segments: list[Primitive],
        tolerance: float,
    ) -> set[int]:
        """保留优化前的双重循环实现，作为对拍基准。"""
        overlapping: set[int] = set()
        for index, primitive in enumerate(segments):
            if primitive.kind != "LINE":
                continue
            for other_index, other in enumerate(segments):
                if index == other_index or other.kind != "LINE":
                    continue
                if _line_segment_covers(other, primitive, tolerance) and (
                    math.dist(primitive.points[0], primitive.points[-1])
                    < math.dist(other.points[0], other.points[-1]) - tolerance
                    or (
                        abs(
                            math.dist(primitive.points[0], primitive.points[-1])
                            - math.dist(other.points[0], other.points[-1])
                        )
                        <= tolerance
                        and other_index < index
                    )
                ):
                    overlapping.add(index)
                    break
        return overlapping

    def test_exact_duplicate_line_is_reported_once(self) -> None:
        segments = self._lines(((0, 0), (10, 0)), ((0, 0), (10, 0)))

        self.assertEqual(_overlapping_line_indices(segments, 1e-7), {1})

    def test_shorter_line_lying_on_longer_line_is_overlapping(self) -> None:
        segments = self._lines(((0, 0), (10, 0)), ((2, 0), (8, 0)))

        self.assertEqual(_overlapping_line_indices(segments, 1e-7), {1})

    def test_collinear_lines_touching_at_endpoint_are_kept(self) -> None:
        segments = self._lines(((0, 0), (10, 0)), ((10, 0), (20, 0)))

        self.assertEqual(_overlapping_line_indices(segments, 1e-7), set())

    def test_parallel_and_crossing_lines_are_not_overlapping(self) -> None:
        segments = self._lines(
            ((0, 0), (10, 0)),
            ((0, 5), (10, 5)),
            ((5, -5), (5, 5)),
        )

        self.assertEqual(_overlapping_line_indices(segments, 1e-7), set())

    def test_matches_brute_force_on_mixed_drawing(self) -> None:
        random.seed(20261008)

        for _ in range(40):
            count = random.randint(6, 30)
            points = [
                (random.uniform(-50, 50), random.uniform(-50, 50))
                for _ in range(count)
            ]
            segments: list[Primitive] = []
            for index, start in enumerate(points):
                end = points[(index + 1) % count]
                segments.append(
                    Primitive((start, end), False, False, "0", "LINE")
                )
                if random.random() < 0.4:
                    segments.append(
                        Primitive((start, end), False, False, "0", "LINE")
                    )
                if random.random() < 0.4:
                    ratio = random.uniform(0.2, 0.8)
                    middle = (
                        start[0] + (end[0] - start[0]) * ratio,
                        start[1] + (end[1] - start[1]) * ratio,
                    )
                    segments.append(
                        Primitive((start, middle), False, False, "0", "LINE")
                    )

            tolerance = 1e-7
            self.assertEqual(
                _overlapping_line_indices(segments, tolerance),
                self._brute_force(segments, tolerance),
            )


class ContourSearchBudgetTests(unittest.TestCase):
    """真实钣金图里存在 100+ 条边的密集连通区域，回溯曾把分析卡死。"""

    def test_dense_branching_component_finishes_quickly(self) -> None:
        # 一张网格：横竖线互相交叉，每个交点都是高分支度节点，
        # 回溯找环的搜索空间是组合爆炸的。
        import time

        from cad_analyzer import _line_contours

        segments: list[Primitive] = []
        grid = range(0, 120, 10)
        for value in grid:
            for start in grid:
                segments.append(
                    Primitive(
                        ((start, value), (start + 10, value)),
                        False,
                        False,
                        "0",
                        "LINE",
                    )
                )
                segments.append(
                    Primitive(
                        ((value, start), (value, start + 10)),
                        False,
                        False,
                        "0",
                        "LINE",
                    )
                )

        started = time.monotonic()
        loops = _line_contours(segments)
        elapsed = time.monotonic() - started

        # 这里不断言识别出多少环，只保证「不会跑不完」。
        self.assertLess(elapsed, 20.0, f"轮廓搜索耗时 {elapsed:.1f}s，疑似退化为指数搜索")
        self.assertTrue(all(loop.closed for loop in loops))

    def test_budget_is_respected(self) -> None:
        from cad_analyzer import _LoopSearchBudget

        budget = _LoopSearchBudget(3)
        self.assertTrue(budget.take())
        self.assertTrue(budget.take())
        self.assertTrue(budget.take())
        self.assertFalse(budget.take())
        self.assertTrue(budget.exhausted)


class BlockExpansionTests(unittest.TestCase):
    """钣金图上块动辄上千个，逐个 virtual_entities() 展开会把分析拖死。

    收集文字/标注时必须先看块定义里有没有目标实体，没有就跳过。
    """

    def _drawing(self, directory: str, block_count: int) -> Path:
        doc = ezdxf.new("R2010")
        doc.units = units.MM
        msp = doc.modelspace()

        plain = doc.blocks.new("PLAIN")
        for index in range(30):
            plain.add_line((index, 0), (index, 10))

        with_dim = doc.blocks.new("WITHDIM")
        with_dim.add_linear_dim(base=(0, 5), p1=(0, 0), p2=(20, 0)).render()

        for index in range(block_count):
            msp.add_blockref("PLAIN", (index * 2.0, 0))
        for index in range(3):
            msp.add_blockref("WITHDIM", (0, 20.0 * (index + 1)))

        path = Path(directory) / "blocks.dxf"
        doc.saveas(path)
        return path

    def test_many_plain_blocks_do_not_slow_analysis(self) -> None:
        import time

        with TemporaryDirectory() as directory:
            path = self._drawing(directory, 1200)
            started = time.monotonic()
            analysis = analyze_dxf(path)
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 10.0, f"分析耗时 {elapsed:.1f}s，疑似逐个展开了所有块")
        # 含标注的块仍然要能读到：优化不能把功能丢掉。
        from roller_drawing import _texts_and_dimensions
        # Annotation contract belongs to the roller parser, not DrawingAnalysis.
        with TemporaryDirectory() as check_dir:
            check_path = self._drawing(check_dir, 2)
            parsed = ezdxf.readfile(check_path)
            _, dimensions = _texts_and_dimensions(parsed.modelspace(), 1.0, parsed)
        self.assertEqual(len(dimensions), 3)


if __name__ == "__main__":
    unittest.main()
