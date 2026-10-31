"""车件：整根外形截一半，并读螺纹和钻孔深度。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest
from pathlib import Path

from cad_analyzer import DrawingAnalysis, DrawingText, Primitive, SketchSegment
from cad_analyzer import DrawingDimension
import tempfile

import ezdxf

from turned_part import (
    _axial_lengths,
    _radius_ladder,
    discover_turned_parts,
    list_turned_drawings,
    plan_turned_part,
    read_turned_notes,
    turned_part_output_path,
)


def _loop(points) -> Primitive:
    closed = points + (points[0],)
    segments = tuple(SketchSegment(a, b) for a, b in zip(closed, closed[1:]))
    return Primitive(closed, True, False, "0", "LINE_LOOP", segments)


def _line(start, end, layer="中心线") -> Primitive:
    return Primitive((start, end), False, False, layer, "LINE", (SketchSegment(start, end),))


def _shaft() -> Primitive:
    points = (
        (0.0, 8.0),
        (40.0, 8.0),
        (40.0, 12.0),
        (80.0, 12.0),
        (80.0, 8.0),
        (120.0, 8.0),
        (120.0, -8.0),
        (80.0, -8.0),
        (80.0, -12.0),
        (40.0, -12.0),
        (40.0, -8.0),
        (0.0, -8.0),
    )
    return _loop(points)


class HalfProfileTests(unittest.TestCase):
    def test_symmetry_keeps_upper_half(self) -> None:
        outline = _shaft()
        analysis = DrawingAnalysis(
            Path("shaft.dxf"),
            "mm",
            (outline,),
            (),
            (outline,),
            (0.0, -12.0, 120.0, 12.0),
            "Model",
        )
        plan = plan_turned_part(analysis)
        self.assertEqual(plan.axis, "horizontal")
        self.assertAlmostEqual(plan.axis_position, 0.0)
        self.assertEqual(plan.axis_source, "symmetry")
        radii = {round(point[1], 3) for point in plan.profile}
        self.assertIn(8.0, radii)
        self.assertIn(12.0, radii)
        self.assertTrue(all(point[1] >= -0.01 for point in plan.profile))
        self.assertAlmostEqual(plan.length_mm, 120.0, places=2)
        self.assertLess(len(plan.profile), len(outline.points))

    def test_explicit_centerline_is_the_axis(self) -> None:
        outline = _loop(
            (
                (0.0, 10.0),
                (50.0, 10.0),
                (50.0, 30.0),
                (0.0, 30.0),
            )
        )
        axis = _line((0.0, 20.0), (50.0, 20.0))
        analysis = DrawingAnalysis(
            Path("axis.dxf"),
            "mm",
            (outline, axis),
            (),
            (outline,),
            (0.0, 10.0, 50.0, 30.0),
            "Model",
        )
        plan = plan_turned_part(analysis)
        self.assertEqual(plan.axis_source, "centerline")
        self.assertAlmostEqual(plan.axis_position, 20.0)
        self.assertAlmostEqual(plan.max_radius_mm, 10.0, places=2)


class OnePartExportTests(unittest.TestCase):
    def test_two_shafts_are_separate_parts(self) -> None:
        left = _shaft()
        right_points = tuple((x + 200.0, y) for x, y in _shaft().points)
        right = _loop(right_points[:-1])
        texts = (
            DrawingText("M10", 20.0, 20.0, 3.0),
            DrawingText("Φ6 深15", 220.0, 20.0, 3.0),
        )
        analysis = DrawingAnalysis(
            Path("two.dxf"),
            "mm",
            (left, right),
            (),
            (left, right),
            (0.0, -12.0, 320.0, 12.0),
            "Model",
            text_entities=texts,
        )
        plans = discover_turned_parts(analysis)
        self.assertEqual(len(plans), 2)
        self.assertEqual([item.label for item in plans], ["件01", "件02"])
        self.assertEqual(plans[0].threads[0].designation, "M10")
        self.assertEqual(plans[0].holes, ())
        self.assertEqual(plans[1].threads, ())
        self.assertAlmostEqual(plans[1].holes[0].depth_mm, 15.0)


class FolderImportTests(unittest.TestCase):
    def test_lists_each_drawing_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "批次"
            nested.mkdir()
            self._write_shaft(root / "轴A.dxf", "M8")
            self._write_shaft(nested / "轴B.dxf", "Φ5 深12")
            (root / "说明.txt").write_text("忽略", encoding="utf-8")
            drawings = list_turned_drawings(root)
            self.assertEqual([path.name for path in drawings], ["轴A.dxf", "轴B.dxf"])
            first = plan_turned_part(
                __import__("cad_analyzer").analyze_cad_file(drawings[0])
            )
            second = plan_turned_part(
                __import__("cad_analyzer").analyze_cad_file(drawings[1])
            )
            self.assertEqual(first.threads[0].designation, "M8")
            self.assertAlmostEqual(second.holes[0].depth_mm, 12.0)
            output = root / "导出"
            output.mkdir()
            self.assertEqual(turned_part_output_path(output, drawings[0]).name, "轴A.SLDPRT")
            turned_part_output_path(output, drawings[0]).write_bytes(b"x")
            self.assertEqual(
                turned_part_output_path(output, drawings[0]).name,
                "轴A_2.SLDPRT",
            )

    def _write_shaft(self, path: Path, note: str) -> None:
        document = ezdxf.new("R2010")
        document.units = ezdxf.units.MM
        document.modelspace().add_lwpolyline(
            [(0, 6), (40, 6), (40, -6), (0, -6)],
            close=True,
        )
        document.modelspace().add_text(note, dxfattribs={"height": 3}).set_placement((5, 12))
        document.saveas(path)


class TurnedNoteTests(unittest.TestCase):
    def test_reads_thread_and_drill_depth(self) -> None:
        outline = _shaft()
        texts = (
            DrawingText("端部 M10×1.5", 10.0, 20.0, 3.0),
            DrawingText("Φ8 深20", 5.0, 16.0, 2.5),
            DrawingText("普通说明", 40.0, 30.0, 2.0),
        )
        analysis = DrawingAnalysis(
            Path("notes.dxf"),
            "mm",
            (outline,),
            (),
            (outline,),
            (0.0, -12.0, 120.0, 12.0),
            "Model",
            text_entities=texts,
        )
        threads, holes = read_turned_notes(analysis)
        self.assertEqual(threads[0].designation, "M10×1.5")
        self.assertAlmostEqual(threads[0].pitch_mm or 0.0, 1.5)
        self.assertEqual(len(holes), 1)
        self.assertAlmostEqual(holes[0].diameter_mm, 8.0)
        self.assertAlmostEqual(holes[0].depth_mm, 20.0)
        plan = plan_turned_part(analysis)
        self.assertEqual(plan.threads[0].designation, "M10×1.5")
        self.assertEqual(len(plan.holes), 1)


class DimensionLadderTests(unittest.TestCase):
    """车件靠图纸标注定尺寸：直径档位和沿轴长度都要读得出来。"""

    def _analysis(self, dimensions) -> DrawingAnalysis:
        outline = _shaft()
        return DrawingAnalysis(
            Path("dims.dxf"),
            "mm",
            (outline,),
            (),
            (outline,),
            (0.0, -12.0, 120.0, 12.0),
            "Model",
            dimensions=dimensions,
        )

    def test_diameter_dimensions_become_radius_ladder(self) -> None:
        analysis = self._analysis(
            (
                DrawingDimension("diameter", 28.0),
                DrawingDimension("diameter", 15.0),
            )
        )
        self.assertEqual(_radius_ladder(analysis), [14.0, 7.5])

    def test_outlier_radius_is_dropped(self) -> None:
        # 图框圆角常标出 R10248 这种值，不能当零件半径。
        analysis = self._analysis(
            (
                DrawingDimension("diameter", 28.0),
                DrawingDimension("diameter", 15.0),
                DrawingDimension("radius", 10248.0),
            )
        )
        self.assertEqual(_radius_ladder(analysis), [14.0, 7.5])

    def test_only_along_axis_lengths_are_used(self) -> None:
        analysis = self._analysis(
            (
                DrawingDimension("linear", 168.0, (0.0, 0.0), (168.0, 0.0)),
                DrawingDimension("linear", 28.0, (10.0, 20.0), (10.0, 48.0)),
                DrawingDimension("diameter", 28.0),
            )
        )
        self.assertEqual(_axial_lengths(analysis, "horizontal"), [168.0])
        self.assertEqual(_axial_lengths(analysis, "vertical"), [28.0])


class SteppedShaftTests(unittest.TestCase):
    """阶梯轴：按图上画出的台阶位置分段，标注只校准数值。"""

    @staticmethod
    def _stepped_analysis() -> DrawingAnalysis:
        # 轴线 y=0；phi20 中段，两端各一段 phi12 轴头。
        half = (
            (0.0, 6.0),
            (20.0, 6.0),
            (20.0, 10.0),
            (100.0, 10.0),
            (100.0, 6.0),
            (120.0, 6.0),
        )
        outline = _loop(half + tuple((x, -y) for x, y in reversed(half)))
        center = _line((-5.0, 0.0), (125.0, 0.0))
        return DrawingAnalysis(
            Path("stepped.dxf"),
            "mm",
            (outline, center),
            (),
            (outline,),
            (0.0, -10.0, 120.0, 10.0),
            "Model",
            dimensions=(
                DrawingDimension("diameter", 20.0),
                DrawingDimension("diameter", 12.0),
                DrawingDimension("linear", 120.0, (0.0, -20.0), (120.0, -20.0)),
                DrawingDimension("linear", 20.0, (0.0, -25.0), (20.0, -25.0)),
                DrawingDimension("linear", 80.0, (20.0, -25.0), (100.0, -25.0)),
                DrawingDimension("linear", 20.0, (100.0, -25.0), (120.0, -25.0)),
            ),
        )

    def test_both_ends_keep_their_step(self) -> None:
        analysis = self._stepped_analysis()
        plan = plan_turned_part(analysis)
        self.assertAlmostEqual(plan.length_mm, 120.0, places=1)
        self.assertAlmostEqual(plan.max_radius_mm * 2.0, 20.0, places=1)
        radii = sorted({round(radius, 2) for _, radius in plan.profile if radius > 0.05})
        self.assertEqual(radii, [6.0, 10.0])

    def test_profile_starts_and_ends_on_axis(self) -> None:
        plan = plan_turned_part(self._stepped_analysis())
        first, last = plan.profile[0], plan.profile[-1]
        self.assertAlmostEqual(first[1], 0.0, places=3)
        self.assertAlmostEqual(last[1], 0.0, places=3)


class TubeBoreTests(unittest.TestCase):
    """套类零件（A-01 皮带座支撑柱）：内孔要挖进剖面，不能当成外径台阶。

    回归背景：Φ15 通孔曾混进外径档位，实心轴上铣出一圈圈细环槽；
    轴线也被剖面里的杂弧圆心带偏 5mm，半径全歪。
    """

    @staticmethod
    def _tube_analysis() -> DrawingAnalysis:
        # 轴线 y=0；外径 phi20 长 74，通孔 phi15 贯穿全长（孔壁线画满）。
        half = ((0.0, 10.0), (74.0, 10.0))
        outline = _loop(half + tuple((x, -y) for x, y in reversed(half)))
        bore_top = _line((0.0, 7.5), (74.0, 7.5), layer="0")
        bore_bottom = _line((0.0, -7.5), (74.0, -7.5), layer="0")
        # 直径标注：竖直方向量，中点落在轴线上（y=0）。
        dims = (
            DrawingDimension("diameter", 20.0),
            DrawingDimension("diameter", 15.0),
            DrawingDimension("linear", 74.0, (0.0, -12.0), (74.0, -12.0)),
            DrawingDimension("linear", 15.0, (10.0, -7.5), (10.0, 7.5), text="%%c<>"),
            DrawingDimension("linear", 15.0, (60.0, -7.5), (60.0, 7.5), text="%%c<>"),
            DrawingDimension("diameter", 12.0, None, None, "内M<>-25深"),
        )
        return DrawingAnalysis(
            Path("tube.dxf"),
            "mm",
            (outline, bore_top, bore_bottom),
            (),
            (outline,),
            (0.0, -10.0, 74.0, 10.0),
            "Model",
            dimensions=dims,
        )

    def test_axis_comes_from_dimension_midpoints(self) -> None:
        analysis = self._tube_analysis()
        import turned_part as tp

        axis, position, source = tp._axis_of(analysis.profiles[0], analysis)
        self.assertEqual(axis, "horizontal")
        self.assertAlmostEqual(position, 0.0, places=1)
        self.assertEqual(source, "dimensions")

    def test_bore_is_detected_not_stepped(self) -> None:
        analysis = self._tube_analysis()
        plan = plan_turned_part(analysis)
        self.assertAlmostEqual(plan.length_mm, 74.0, places=1)
        self.assertAlmostEqual(plan.max_radius_mm * 2.0, 20.0, places=1)
        # 环形剖面：最小半径 = 孔半径 7.5，不落回轴线。
        radii = sorted({round(radius, 2) for _, radius in plan.profile})
        self.assertEqual(radii, [7.5, 10.0])

    def test_internal_thread_read_from_dimension(self) -> None:
        analysis = self._tube_analysis()
        plan = plan_turned_part(analysis)
        designations = [thread.designation for thread in plan.threads]
        self.assertIn("M12", designations)
        note = next(
            thread for thread in plan.threads if thread.designation == "M12"
        )
        # 占位符换成真实数值，备注可读。
        self.assertIn("内M12-25深", note.text)

    def test_long_thin_section_is_not_mistaken_for_bore(self) -> None:
        # 细长外径台阶：外径线只盖住小头，不能按内孔处理。
        analysis = self._stepped_shaft_with_long_thin_section()
        plan = plan_turned_part(analysis)
        # 实心轴：剖面必须落回轴线。
        self.assertAlmostEqual(plan.profile[0][1], 0.0, places=3)
        radii = sorted({round(radius, 2) for _, radius in plan.profile if radius > 0.05})
        self.assertIn(7.5, radii)

    @staticmethod
    def _stepped_shaft_with_long_thin_section() -> DrawingAnalysis:
        # phi20 只有左端 10 长，phi15 细轴占剩下 110：外径线盖不住孔。
        half = ((0.0, 10.0), (10.0, 10.0), (10.0, 7.5), (120.0, 7.5))
        outline = _loop(half + tuple((x, -y) for x, y in reversed(half)))
        return DrawingAnalysis(
            Path("longthin.dxf"),
            "mm",
            (outline,),
            (),
            (outline,),
            (0.0, -10.0, 120.0, 10.0),
            "Model",
            dimensions=(
                DrawingDimension("diameter", 20.0),
                DrawingDimension("diameter", 15.0),
                DrawingDimension("linear", 120.0, (0.0, -12.0), (120.0, -12.0)),
            ),
        )


class SteppedEndThreadBoreTests(unittest.TestCase):
    """A-01 皮带座支撑柱：Φ20 轴身、两端各 3mm 车到 Φ15、右端 M12 盲孔。

    回归背景：Φ15 本来只是两端的外圆台阶，两条线中间断开 68mm，
    旧逻辑按「跨度够长」把 Φ15 当成了通孔，把整根轴掏成了管子，
    同时 3mm 台阶和孔被丢掉。
    """

    @staticmethod
    def _analysis() -> DrawingAnalysis:
        points = (
            (0.0, 7.5),
            (3.0, 7.5),
            (3.0, 10.0),
            (71.0, 10.0),
            (71.0, 7.5),
            (74.0, 7.5),
            (74.0, -7.5),
            (71.0, -7.5),
            (71.0, -10.0),
            (3.0, -10.0),
            (3.0, -7.5),
            (0.0, -7.5),
        )
        outline = _loop(points)
        # 右端 M12 内螺纹孔：孔壁 Φ12 从 74 深到 44，孔底带 120° 钻尖到 39.64。
        walls = (
            _line((44.0, 6.0), (74.0, 6.0), layer="0"),
            _line((44.0, -6.0), (74.0, -6.0), layer="0"),
            _line((44.0, 6.0), (39.64, 0.0), layer="0"),
            _line((44.0, -6.0), (39.64, 0.0), layer="0"),
        )
        dims = (
            DrawingDimension("diameter", 20.0),
            DrawingDimension("diameter", 15.0),
            DrawingDimension("linear", 3.0, (0.0, 11.0), (3.0, 11.0)),
            DrawingDimension("linear", 68.0, (3.0, 12.0), (71.0, 12.0)),
            DrawingDimension("linear", 74.0, (0.0, -9.0), (74.0, -9.0)),
            DrawingDimension("linear", 30.0, (74.0, -6.0), (44.0, -6.0)),
            DrawingDimension("linear", 15.0, (0.0, 7.5), (0.0, -7.5), text="%%c<>"),
            DrawingDimension("linear", 15.0, (74.0, 7.5), (74.0, -7.5), text="%%c<>"),
            DrawingDimension("linear", 12.0, (74.0, 6.0), (74.0, -6.0), text="内M<>-25深"),
        )
        return DrawingAnalysis(
            Path("a01.dxf"),
            "mm",
            (outline, *walls),
            (),
            (outline,),
            (0.0, -10.0, 74.0, 10.0),
            "Model",
            dimensions=dims,
        )

    def test_both_ends_are_stepped_three_millimetres(self) -> None:
        plan = plan_turned_part(self._analysis())
        self.assertAlmostEqual(plan.length_mm, 74.0, places=1)
        # 台阶位置：x=3 由 Φ15 跳到 Φ20，x=71 又落回 Φ15。
        for expected in (
            (0.0, 7.5),
            (3.0, 7.5),
            (3.0, 10.0),
            (71.0, 10.0),
            (71.0, 7.5),
            (74.0, 7.5),
        ):
            self.assertTrue(
                any(
                    abs(x - expected[0]) <= 0.05 and abs(radius - expected[1]) <= 0.05
                    for x, radius in plan.profile
                ),
                f"剖面缺少点 {expected}：{plan.profile}",
            )

    def test_thread_hole_is_blind_with_drill_point(self) -> None:
        plan = plan_turned_part(self._analysis())
        radii = [radius for _, radius in plan.profile]
        # M12 粗牙底孔 Φ10.1：攻丝前钻的孔，不是公称 Φ12。
        hole = min(radius for radius in radii if radius > 0.05)
        self.assertAlmostEqual(hole, 5.06, places=2)
        # 孔口在右端面，直壁到 x=44（深 30），钻尖再往里 4.36。
        xs = [x for x, radius in plan.profile if abs(radius - hole) < 1e-6]
        self.assertAlmostEqual(max(xs), 74.0, places=2)
        self.assertAlmostEqual(min(xs), 44.0, places=2)
        apex = [x for x, radius in plan.profile if radius <= 1e-6 and x > 0.0]
        self.assertAlmostEqual(min(apex), 39.64, places=1)

    def test_split_end_lines_are_not_a_through_bore(self) -> None:
        import turned_part as tp

        analysis = self._analysis()
        outline = analysis.profiles[0]
        axis, position, _source = tp._axis_of(outline, analysis)
        radii = tp._radius_ladder(analysis)
        segments = tp._matching_segments(analysis, axis, position, radii)
        bore_radius, _window = tp._detect_bore(segments, radii)
        self.assertIsNone(bore_radius)

    def test_tap_drill_from_major_diameter(self) -> None:
        import turned_part as tp

        self.assertAlmostEqual(tp._tap_drill_diameter(12.0), 10.11, places=2)
        self.assertAlmostEqual(tp._tap_drill_diameter(8.0), 6.65, places=2)
        # 非标尺寸退回按 0.85 倍估算。
        self.assertAlmostEqual(tp._tap_drill_diameter(13.0), 11.05, places=2)


class ThreadSyncTests(unittest.TestCase):
    """螺纹要和底孔同步长在模型上。

    用户要求：孔是钻出来的（120° 钻尖），螺纹不能只写进备注，
    要在模型里同步做成装饰螺纹线。生成前得先有「孔口 + 大径 + 有效深」
    这组数，才能定位孔口圆边、插入螺纹特征。
    """

    @staticmethod
    def _plan():
        return plan_turned_part(SteppedEndThreadBoreTests._analysis())

    def test_plan_carries_bore_and_thread_geometry(self) -> None:
        plan = self._plan()
        self.assertEqual(len(plan.bores), 1)
        bore = plan.bores[0]
        self.assertAlmostEqual(bore.radius_mm, 10.11 / 2.0, places=2)
        self.assertEqual(bore.designation, "M12")
        self.assertAlmostEqual(bore.major_mm, 12.0, places=2)
        self.assertAlmostEqual(bore.pitch_mm, 1.75, places=3)
        # 「内M12-25深」里的 25 是有效螺纹深度。
        self.assertAlmostEqual(bore.thread_depth_mm, 25.0, places=2)
        # 孔口在右端面，直壁到 x=44，钻尖到 39.64。
        self.assertAlmostEqual(bore.opening_mm, 74.0, places=2)
        self.assertAlmostEqual(bore.bottom_mm, 44.0, places=2)
        self.assertAlmostEqual(bore.apex_mm, 39.64, places=1)
        self.assertEqual(bore.side, "high")

    def test_thread_depth_reads_note_or_falls_back_to_bore(self) -> None:
        import turned_part as tp

        self.assertAlmostEqual(tp._thread_depth(12.0, "内M12-25深", 30.0), 25.0)
        self.assertAlmostEqual(tp._thread_depth(12.0, "M12 深 18", 30.0), 18.0)
        # 没写深度时，从孔深里留出 2.5 倍螺距的钻尖余量。
        self.assertAlmostEqual(tp._thread_depth(8.0, "M8", 20.0), 16.88, places=2)

    def test_world_point_maps_sketch_to_model_space(self) -> None:
        import turned_part as tp

        frame = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0))
        point = tp._world_point(frame, 74.0, 5.055)
        self.assertAlmostEqual(point[0], 0.074, places=6)
        self.assertAlmostEqual(point[1], 0.005055, places=6)
        self.assertAlmostEqual(point[2], 0.0, places=6)

    def test_discovery_keeps_thread_bore(self) -> None:
        plans = discover_turned_parts(SteppedEndThreadBoreTests._analysis())
        self.assertEqual(len(plans), 1)
        self.assertEqual(len(plans[0].bores), 1)
        self.assertEqual(plans[0].bores[0].designation, "M12")


if __name__ == "__main__":
    unittest.main()
