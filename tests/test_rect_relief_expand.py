"""矩形释放槽：拼环不对角捷径；step1 +1.0mm，之后每级 +0.5mm。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest

from cad_analyzer import Primitive, SketchSegment, _line_contours
from profile_sanitize import sanitize_closed_profile
from solidworks_generator import (
    RECT_RELIEF_EXPAND_MM,
    RECT_RELIEF_FIRST_EXPAND_MM,
    apply_rectangular_relief_expansion,
    axis_aligned_rect_bounds,
    ensure_intersection_reliefs,
    expand_axis_aligned_rect_profile,
    expand_rectangular_relief_notches,
    rect_relief_extra_mm,
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


def _rect_with_corner_notches(
    width: float,
    height: float,
    notch: float,
) -> list[Primitive]:
    r = float(notch)
    w = float(width)
    h = float(height)
    edges = [
        ((r, 0.0), (w - r, 0.0)),
        ((w - r, 0.0), (w - r, r)),
        ((w - r, r), (w, r)),
        ((w, r), (w, h - r)),
        ((w, h - r), (w - r, h - r)),
        ((w - r, h - r), (w - r, h)),
        ((w - r, h), (r, h)),
        ((r, h), (r, h - r)),
        ((r, h - r), (0.0, h - r)),
        ((0.0, h - r), (0.0, r)),
        ((0.0, r), (r, r)),
        ((r, r), (r, 0.0)),
    ]
    return [_line(a, b) for a, b in edges]


def _diags(points: tuple[tuple[float, float], ...]) -> list:
    return [
        (start, end)
        for start, end in zip(points, points[1:])
        if abs(end[0] - start[0]) > 0.05 and abs(end[1] - start[1]) > 0.05
    ]


class OuterContourStepTests(unittest.TestCase):
    def test_rectangular_step_on_a_continuous_edge_stays_outer(self) -> None:
        """台阶口开在长边中部时，仍是外轮廓，不当成没接上的线。"""

        edges = [
            ((0.0, 0.0), (100.0, 0.0)),
            ((100.0, 0.0), (100.0, 60.0)),
            ((100.0, 60.0), (0.0, 60.0)),
            ((0.0, 60.0), (0.0, 0.0)),
            ((30.0, 0.0), (30.0, 8.0)),
            ((30.0, 8.0), (38.0, 8.0)),
            ((38.0, 8.0), (38.0, 0.0)),
        ]
        contours = _line_contours([_line(start, end) for start, end in edges])
        outer = max(
            contours,
            key=lambda item: (
                max(point[0] for point in item.points) - min(point[0] for point in item.points)
            )
            * (
                max(point[1] for point in item.points) - min(point[1] for point in item.points)
            ),
        )
        pts = {(round(point[0], 3), round(point[1], 3)) for point in outer.points}
        self.assertTrue({(30.0, 8.0), (38.0, 8.0)} <= pts)
        self.assertEqual(_diags(outer.points), [])


class SnapPreservesTinyNotchTests(unittest.TestCase):
    def test_half_mm_notch_on_large_part_no_diagonal(self) -> None:
        contours = _line_contours(_rect_with_corner_notches(1000.0, 800.0, 0.5))
        self.assertEqual(len(contours), 1)
        outer = contours[0]
        pts = {(round(p[0], 5), round(p[1], 5)) for p in outer.points}
        expected = {
            (0.5, 0.5),
            (999.5, 0.5),
            (999.5, 799.5),
            (0.5, 799.5),
        }
        self.assertTrue(
            expected <= pts,
            f"missing notch inners {expected - pts}",
        )
        self.assertEqual(_diags(outer.points), [])

    def test_tall_narrow_slot_with_diagonal_chord_follows_notch(self) -> None:
        slot_w, slot_d = 1.0, 8.0
        sx0, sx1 = 90.0, 91.0
        edges = [
            ((0.0, 0.0), (sx0, 0.0)),
            ((sx0, 0.0), (sx0, slot_d)),
            ((sx0, slot_d), (sx1, slot_d)),
            ((sx1, slot_d), (sx1, 0.0)),
            ((sx1, 0.0), (200.0, 0.0)),
            ((200.0, 0.0), (200.0, 100.0)),
            ((200.0, 100.0), (0.0, 100.0)),
            ((0.0, 100.0), (0.0, 0.0)),
            ((sx0, 0.0), (sx1, slot_d)),
        ]
        contours = _line_contours([_line(a, b) for a, b in edges])
        self.assertGreaterEqual(len(contours), 1)
        outer = max(
            contours,
            key=lambda item: (
                max(p[0] for p in item.points) - min(p[0] for p in item.points)
            )
            * (max(p[1] for p in item.points) - min(p[1] for p in item.points)),
        )
        pts = {(round(p[0], 5), round(p[1], 5)) for p in outer.points}
        self.assertTrue({(sx0, slot_d), (sx1, slot_d)} <= pts)
        self.assertEqual(_diags(outer.points), [])


class RectReliefExpandTests(unittest.TestCase):
    def _notched_profile(self, notch: float = 2.0) -> Primitive:
        contours = _line_contours(_rect_with_corner_notches(100.0, 80.0, notch))
        return sanitize_closed_profile(contours[0], min_edge_mm=0.05)

    def test_rect_relief_extra_mm_schedule(self) -> None:
        self.assertEqual(RECT_RELIEF_FIRST_EXPAND_MM, 1.0)
        self.assertEqual(RECT_RELIEF_EXPAND_MM, 0.5)
        self.assertAlmostEqual(rect_relief_extra_mm(0), 0.0)
        self.assertAlmostEqual(rect_relief_extra_mm(1), 1.0)
        self.assertAlmostEqual(rect_relief_extra_mm(2), 1.5)
        self.assertAlmostEqual(rect_relief_extra_mm(3), 2.0)
        self.assertAlmostEqual(rect_relief_extra_mm(5), 3.0)

    def test_step1_expands_notch_by_first_mm(self) -> None:
        profile = self._notched_profile(2.0)
        step0 = expand_rectangular_relief_notches(profile, 0.0)
        step1 = expand_rectangular_relief_notches(
            profile, rect_relief_extra_mm(1)
        )
        pts0 = {(round(p[0], 6), round(p[1], 6)) for p in step0.points}
        pts1 = {(round(p[0], 6), round(p[1], 6)) for p in step1.points}
        self.assertIn((2.0, 2.0), pts0)
        self.assertIn((3.0, 3.0), pts1)
        self.assertNotIn((2.0, 2.0), pts1)

    def test_apply_step_scales_with_relief_step(self) -> None:
        profile = self._notched_profile(1.5)
        holes: tuple = ()
        p1, _, n1 = apply_rectangular_relief_expansion(profile, holes, 1)
        p2, _, n2 = apply_rectangular_relief_expansion(profile, holes, 2)
        self.assertGreaterEqual(n1, 1)
        self.assertGreaterEqual(n2, 1)
        pts1 = {(round(p[0], 6), round(p[1], 6)) for p in p1.points}
        pts2 = {(round(p[0], 6), round(p[1], 6)) for p in p2.points}
        self.assertIn((2.5, 2.5), pts1)  # 1.5+1.0
        self.assertIn((3.0, 3.0), pts2)  # 1.5+1.5

    def test_l_corner_relief_grows_one_side_toward_panel(self) -> None:
        """QL-5050 #247 式 L 形角部释放槽：只朝板面（多数凹角方向）单边扩。"""
        ring = [
            (10.0, 0.0), (10.0, 20.0), (11.0, 20.0), (11.0, 21.5),
            (9.0, 21.5), (9.0, 18.5), (0.0, 18.5), (0.0, 60.0),
            (60.0, 60.0), (60.0, 0.0),
        ]
        edges = [_line(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]
        profile = sanitize_closed_profile(_line_contours(edges)[0], min_edge_mm=0.05)
        grown = expand_rectangular_relief_notches(profile, rect_relief_extra_mm(1))
        pts = {(round(p[0], 6), round(p[1], 6)) for p in grown.points}
        # 内角 (11,21.5) -> (12,22.5)；外侧边 x=9、台阶 y=20 不动
        self.assertIn((12.0, 22.5), pts)
        self.assertIn((9.0, 22.5), pts)
        self.assertIn((9.0, 18.5), pts)
        self.assertIn((12.0, 20.0), pts)
        self.assertIn((10.0, 20.0), pts)
        self.assertEqual(_diags(grown.points), [])

    def _u_slot_profile(self) -> Primitive:
        edges = [
            ((0.0, 0.0), (50.0, 0.0)),
            ((50.0, 0.0), (50.0, 6.0)),
            ((50.0, 6.0), (58.0, 6.0)),
            ((58.0, 6.0), (58.0, 0.0)),
            ((58.0, 0.0), (120.0, 0.0)),
            ((120.0, 0.0), (120.0, 80.0)),
            ((120.0, 80.0), (0.0, 80.0)),
            ((0.0, 80.0), (0.0, 0.0)),
        ]
        contours = _line_contours([_line(start, end) for start, end in edges])
        return sanitize_closed_profile(contours[0], min_edge_mm=0.05)

    def test_u_slot_deepens_only_toward_panel(self) -> None:
        """对称 U 槽：深度整份朝板面（越过中心线），不再两侧各推一半。"""

        profile = self._u_slot_profile()
        bend = Primitive(
            ((10.0, 4.0), (110.0, 4.0)),
            False,
            True,
            "中心线",
            "LINE",
        )
        grown = expand_rectangular_relief_notches(
            profile,
            rect_relief_extra_mm(1),
            bend_lines=(bend,),
        )
        pts = {(round(point[0], 6), round(point[1], 6)) for point in grown.points}
        self.assertIn((0.0, 0.0), pts)
        self.assertIn((120.0, 0.0), pts)
        inner = [point for point in pts if abs(point[1] - 7.0) < 1e-6]
        self.assertGreaterEqual(len(inner), 2)
        self.assertFalse(any(abs(point[1] - 6.0) < 1e-6 for point in pts))
        xs = sorted(point[0] for point in inner)
        self.assertAlmostEqual(xs[-1] - xs[0], 9.0, places=3)
        self.assertTrue(50.0 in xs or 58.0 in xs)

    def test_apply_step1_then_half_millimetre_on_panel_side(self) -> None:
        profile = self._u_slot_profile()
        bend = Primitive(
            ((10.0, 4.0), (110.0, 4.0)),
            False,
            True,
            "中心线",
            "LINE",
        )
        bends = (bend,)
        step1, _, count1 = apply_rectangular_relief_expansion(
            profile, (), 1, bends
        )
        step2, _, count2 = apply_rectangular_relief_expansion(
            profile, (), 2, bends
        )
        self.assertGreaterEqual(count1, 1)
        self.assertGreaterEqual(count2, 1)

        def inner_y(item: Primitive) -> float:
            return max(point[1] for point in item.points if point[1] < 20.0)

        self.assertAlmostEqual(inner_y(step1), 7.0, places=3)
        self.assertAlmostEqual(inner_y(step2), 7.5, places=3)
        self.assertAlmostEqual(
            inner_y(step2) - inner_y(step1),
            RECT_RELIEF_EXPAND_MM,
            places=3,
        )

    def test_missing_intersection_gets_minimal_rect_on_panel_side(self) -> None:
        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        vertical = Primitive(((30.0, 5.0), (30.0, 75.0)), False, True, "折弯线", "LINE")
        horizontal = Primitive(((5.0, 20.0), (95.0, 20.0)), False, True, "折弯线", "LINE")
        _profile, holes, count = ensure_intersection_reliefs(
            outer,
            (),
            (vertical, horizontal),
            2.0,
            1.0,
            relief_step=1,
        )
        self.assertEqual(count, 1)
        bounds = axis_aligned_rect_bounds(holes[0][0])
        assert bounds is not None
        self.assertAlmostEqual(bounds[0], 30.0, places=3)
        self.assertAlmostEqual(bounds[2], 31.0, places=3)
        self.assertAlmostEqual(bounds[1], 20.0, places=3)
        self.assertAlmostEqual(bounds[3], 21.0, places=3)
        self.assertEqual(_diags(holes[0][0].points), [])

    def test_missing_slot_grows_a_little_in_both_directions(self) -> None:
        """不预开固定长槽。step0 不动；之后向上、向内各加同一小段。"""

        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        vertical = Primitive(((30.0, 5.0), (30.0, 75.0)), False, True, "折弯线", "LINE")
        horizontal = Primitive(((5.0, 20.0), (95.0, 20.0)), False, True, "折弯线", "LINE")
        _profile, holes, count = ensure_intersection_reliefs(
            outer, (), (vertical, horizontal), 2.5, 1.0, relief_step=0
        )
        self.assertEqual(count, 0)
        self.assertEqual(holes, ())
        _profile, holes, _count = ensure_intersection_reliefs(
            outer, (), (vertical, horizontal), 2.5, 1.0, relief_step=2
        )
        bounds = axis_aligned_rect_bounds(holes[0][0])
        assert bounds is not None
        self.assertAlmostEqual(bounds[2] - bounds[0], 1.5, places=3)
        self.assertAlmostEqual(bounds[3] - bounds[1], 1.5, places=3)

    def test_existing_hole_near_intersection_is_kept(self) -> None:
        outer = Primitive(
            ((0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0), (0.0, 0.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        hole = Primitive(
            ((28.0, 18.0), (36.0, 18.0), (36.0, 26.0), (28.0, 26.0), (28.0, 18.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        vertical = Primitive(((30.0, 5.0), (30.0, 75.0)), False, True, "折弯线", "LINE")
        horizontal = Primitive(((5.0, 20.0), (95.0, 20.0)), False, True, "折弯线", "LINE")
        _profile, holes, count = ensure_intersection_reliefs(
            outer,
            ((hole, hole.points),),
            (vertical, horizontal),
            2.0,
            1.0,
            relief_step=1,
        )
        self.assertEqual(count, 0)
        self.assertEqual(len(holes), 1)

    def test_rect_hole_grows_length_and_width(self) -> None:
        hole = Primitive(
            ((10.0, 10.0), (14.0, 10.0), (14.0, 12.0), (10.0, 12.0), (10.0, 10.0)),
            True,
            False,
            "0",
            "LINE_LOOP",
        )
        bounds0 = axis_aligned_rect_bounds(hole)
        assert bounds0 is not None
        grown = expand_axis_aligned_rect_profile(hole, 0.5)
        bounds1 = axis_aligned_rect_bounds(grown)
        assert bounds1 is not None
        self.assertAlmostEqual(bounds1[2] - bounds1[0], 4.5, places=6)
        self.assertAlmostEqual(bounds1[3] - bounds1[1], 2.5, places=6)


if __name__ == "__main__":
    unittest.main()
