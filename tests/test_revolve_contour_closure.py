"""旋转轮廓必须在写入 SolidWorks 之前闭合成圆上的弧。

f09/f15/f19 的计划长度和半径是对的，draw() 仍报「旋转轮廓没有闭合」。
圆角被拟合成弧之后，若按 Create3PointArc(start, via, end) 写入，接口把
第二点当终点，弧停在 via，下一条线从 end 起，缝有零点几毫米。
这里不连 SolidWorks，只检查密封后的段和 CreateArc 参数。
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from turned_generate import (
    SketchPathSegment,
    build_turned,
    contour_joint_gap,
    prepare_profile_sketch,
    revolve_arc_meters,
    seal_revolve_contour,
)
from turned_part import TurnedPartPlan


def _tessellate(center, radius, start_angle, end_angle):
    sweep = end_angle - start_angle
    count = max(2, math.ceil(abs(sweep) / (math.pi / 24.0)))
    points = []
    for index in range(count + 1):
        angle = start_angle + sweep * index / count
        points.append(
            (
                center[0] + radius * math.cos(angle),
                center[1] + radius * math.sin(angle),
            )
        )
    return points


def _shoulder_fillet():
    """台阶轴，肩部 R1.5。圆弧按分析器的步长拆成折线，和车间 DXF 一样。"""

    radius = 1.5
    center = (40.0 - radius, 12.0 - radius)
    points = [(0.0, 0.0), (0.0, 8.0), (center[0], 8.0)]
    arc = _tessellate(center, radius, -math.pi / 2.0, 0.0)
    points.extend(arc[1:])
    points.extend([(40.0, 12.0), (80.0, 12.0), (80.0, 0.0)])
    return points


def _groove_and_fillet():
    """外圆角加凹退刀槽。两段弧方向相反，密封不能把其中一段翻成优弧。"""

    points = [(0.0, 0.0), (0.0, 10.0), (18.0, 10.0)]
    # 凹槽：圆心在外圆上，从左到右经过最低点。
    points.extend(_tessellate((22.0, 10.0), 2.0, math.pi, math.tau)[1:])
    points.append((30.0, 10.0))
    fillet_center = (40.0 - 1.0, 14.0 - 1.0)
    points.append((fillet_center[0], 10.0))
    points.extend(_tessellate(fillet_center, 1.0, -math.pi / 2.0, 0.0)[1:])
    points.extend([(40.0, 14.0), (70.0, 14.0), (70.0, 0.0)])
    return points


def _legacy_three_point_gap(segments) -> float:
    """旧调用 Create3PointArc(start, via, end) 时，弧的终点实际是 via。"""

    gaps = []
    for first, second in zip(segments, segments[1:] + segments[:1]):
        end = first.via if first.kind == "arc" and first.via is not None else first.end
        gaps.append(math.dist(end, second.start))
    return max(gaps) if gaps else 0.0


def _via_on_directed_arc(segment) -> bool:
    center = segment.center
    start_angle = math.atan2(segment.start[1] - center[1], segment.start[0] - center[0])
    end_angle = math.atan2(segment.end[1] - center[1], segment.end[0] - center[0])
    via_angle = math.atan2(segment.via[1] - center[1], segment.via[0] - center[0])
    if segment.direction > 0:
        sweep = (end_angle - start_angle) % math.tau
        via = (via_angle - start_angle) % math.tau
    else:
        sweep = (start_angle - end_angle) % math.tau
        via = (start_angle - via_angle) % math.tau
    return 0.0 <= via <= sweep + 1e-6


def _radial_error(segment) -> float:
    radius = math.dist(segment.center, segment.via)
    return max(
        abs(math.dist(segment.center, segment.start) - radius),
        abs(math.dist(segment.center, segment.end) - radius),
    )


def _directed_sweep_deg(segment) -> float:
    center = segment.center
    start_angle = math.atan2(segment.start[1] - center[1], segment.start[0] - center[0])
    end_angle = math.atan2(segment.end[1] - center[1], segment.end[0] - center[0])
    if segment.direction > 0:
        sweep = (end_angle - start_angle) % math.tau
    else:
        sweep = (start_angle - end_angle) % math.tau
    return math.degrees(sweep)


class RevolveContourClosureTests(unittest.TestCase):
    def test_shoulder_fillet_seals_where_three_point_order_opens(self) -> None:
        sketch = prepare_profile_sketch(
            _shoulder_fillet(),
            length_mm=80.0,
            max_radius_mm=12.0,
        )
        arcs = [segment for segment in sketch.segments if segment.kind == "arc"]
        self.assertGreaterEqual(len(arcs), 1)
        self.assertEqual(contour_joint_gap(sketch.segments), 0.0)
        self.assertGreater(_legacy_three_point_gap(sketch.segments), 0.2)
        for arc in arcs:
            self.assertIn(arc.direction, (-1, 1))
            self.assertLess(_radial_error(arc), 1e-6)
            self.assertTrue(_via_on_directed_arc(arc))
            sweep = _directed_sweep_deg(arc)
            self.assertLess(sweep, 180.0)
        self.assertAlmostEqual(sketch.length_mm, 80.0, places=2)
        self.assertAlmostEqual(sketch.max_radius_mm, 12.0, places=2)
        xs = [point[0] for segment in sketch.segments for point in (segment.start, segment.end)]
        ys = [point[1] for segment in sketch.segments for point in (segment.start, segment.end)]
        self.assertAlmostEqual(max(xs) - min(xs), 80.0, places=3)
        self.assertAlmostEqual(max(ys), 12.0, places=3)

    def test_groove_and_fillet_keep_both_arc_sides(self) -> None:
        sketch = prepare_profile_sketch(
            _groove_and_fillet(),
            length_mm=70.0,
            max_radius_mm=14.0,
        )
        arcs = [segment for segment in sketch.segments if segment.kind == "arc"]
        self.assertGreaterEqual(len(arcs), 2)
        self.assertEqual(contour_joint_gap(sketch.segments), 0.0)
        self.assertGreater(_legacy_three_point_gap(sketch.segments), 0.2)
        for arc in arcs:
            self.assertLess(_radial_error(arc), 1e-6)
            self.assertTrue(_via_on_directed_arc(arc))
            self.assertLessEqual(_directed_sweep_deg(arc), 180.0 + 1e-3)

    def test_stepped_lines_stay_closed(self) -> None:
        profile = (
            (0.0, 0.0),
            (0.0, 8.0),
            (40.0, 8.0),
            (40.0, 12.0),
            (80.0, 12.0),
            (80.0, 0.0),
        )
        sketch = prepare_profile_sketch(profile, length_mm=80.0, max_radius_mm=12.0)
        self.assertTrue(sketch.segments)
        self.assertTrue(all(segment.kind == "line" for segment in sketch.segments))
        self.assertEqual(contour_joint_gap(sketch.segments), 0.0)
        self.assertEqual(sketch.segments[0].start, sketch.segments[-1].end)

    def test_dxf_crack_at_fillet_is_welded(self) -> None:
        center = (40.0, 10.0)
        radius = 2.0
        start = (38.0, 10.0)
        via = (40.0 - math.sqrt(2.0), 10.0 - math.sqrt(2.0))
        end = (40.0, 8.0)
        crack = 0.03
        segments = (
            SketchPathSegment("line", (0.0, 0.0), (0.0, 10.0)),
            SketchPathSegment("line", (0.0, 10.0), (start[0], start[1] + crack)),
            SketchPathSegment("arc", start, end, via),
            SketchPathSegment("line", (end[0] + crack, end[1]), (40.0, 12.0)),
            SketchPathSegment("line", (40.0, 12.0), (80.0, 12.0)),
            SketchPathSegment("line", (80.0, 12.0), (80.0, 0.0)),
            SketchPathSegment("line", (80.0, 0.0), (0.0, 0.0)),
        )
        sealed = seal_revolve_contour(segments)
        self.assertEqual(contour_joint_gap(sealed), 0.0)
        arcs = [segment for segment in sealed if segment.kind == "arc"]
        self.assertEqual(len(arcs), 1)
        self.assertLess(_radial_error(arcs[0]), 1e-6)
        self.assertTrue(_via_on_directed_arc(arcs[0]))
        # 焊接只吃掉这条缝，不把台阶挪出容差。
        self.assertLess(math.dist(arcs[0].start, start), crack + 1e-6)
        self.assertLess(math.dist(arcs[0].end, end), crack + 1e-6)

    def test_large_gap_is_not_invented_away(self) -> None:
        segments = (
            SketchPathSegment("line", (0.0, 0.0), (0.0, 10.0)),
            SketchPathSegment("line", (0.0, 10.0), (20.0, 10.0)),
            SketchPathSegment("line", (21.0, 10.0), (40.0, 10.0)),
            SketchPathSegment("line", (40.0, 10.0), (40.0, 0.0)),
            SketchPathSegment("line", (40.0, 0.0), (0.0, 0.0)),
        )
        with self.assertRaisesRegex(ValueError, "还有 1.0000 mm 的缝"):
            seal_revolve_contour(segments)

    def test_create_arc_arguments_use_center_start_end(self) -> None:
        sketch = prepare_profile_sketch(
            _shoulder_fillet(),
            length_mm=80.0,
            max_radius_mm=12.0,
        )
        arc = next(segment for segment in sketch.segments if segment.kind == "arc")
        args = revolve_arc_meters(arc)
        self.assertEqual(len(args), 10)
        self.assertEqual(args[0:3], (arc.center[0] / 1000.0, arc.center[1] / 1000.0, 0.0))
        self.assertEqual(args[3:6], (arc.start[0] / 1000.0, arc.start[1] / 1000.0, 0.0))
        self.assertEqual(args[6:9], (arc.end[0] / 1000.0, arc.end[1] / 1000.0, 0.0))
        self.assertEqual(args[9], arc.direction)
        source = Path(__file__).resolve().parents[1].joinpath("src/turned_part.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Create3PointArc", source)
        self.assertIn("CreateArc(*revolve_arc_meters(piece))", source)

    def test_build_turned_keeps_sealed_fillet(self) -> None:
        profile = tuple(_shoulder_fillet())
        if math.dist(profile[0], profile[-1]) > 1e-6:
            profile = profile + (profile[0],)
        plan = TurnedPartPlan(
            "horizontal",
            0.0,
            "symmetry",
            profile,
            (),
            (),
        )
        build = build_turned(plan)
        self.assertIsNotNone(build.revolve)
        self.assertEqual(contour_joint_gap(build.revolve.segments), 0.0)
        self.assertAlmostEqual(build.length_mm, 80.0, places=2)
        self.assertAlmostEqual(build.revolve.max_radius_mm, 12.0, places=2)

    def test_sealing_twice_stays_closed(self) -> None:
        sketch = prepare_profile_sketch(
            _shoulder_fillet(),
            length_mm=80.0,
            max_radius_mm=12.0,
        )
        again = seal_revolve_contour(sketch.segments)
        self.assertEqual(contour_joint_gap(again), 0.0)
        self.assertEqual(len(again), len(sketch.segments))
        for first, second in zip(sketch.segments, again):
            self.assertEqual(first.kind, second.kind)
            self.assertEqual(first.direction, second.direction)
            self.assertLess(math.dist(first.start, second.start), 1e-6)
            self.assertLess(math.dist(first.end, second.end), 1e-6)


if __name__ == "__main__":
    unittest.main()
