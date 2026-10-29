# -*- coding: utf-8 -*-
"""贴板边的释放槽要跨越板边开成缺口（「有些要朝板外扩」）。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "src"))


import unittest

from cad_analyzer import Primitive, SketchSegment
from solidworks_generator import (
    apply_rectangular_relief_expansion,
    convert_border_hole_to_notch,
    ensure_intersection_reliefs,
    expand_rectangular_relief_notches,
)


def _rect(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    kind: str = "LINE_LOOP",
) -> Primitive:
    ring = (
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
        (min_x, min_y),
    )
    segments = tuple(
        SketchSegment(start, end) for start, end in zip(ring, ring[1:])
    )
    return Primitive(ring, True, False, kind, "LINE_LOOP", segments)


def _bend(start: tuple[float, float], end: tuple[float, float]) -> Primitive:
    return Primitive(
        (start, end),
        False,
        True,
        "折弯线",
        "LINE",
        (SketchSegment(start, end),),
    )


def _ring(profile: Primitive) -> list[tuple[float, float]]:
    points = list(profile.points)
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


def _area(profile: Primitive) -> float:
    ring = _ring(profile)
    total = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


class BorderHoleToNotchTests(unittest.TestCase):
    def test_border_hole_becomes_notch(self) -> None:
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 40.0, 10.0, 50.0, kind="RELIEF")
        notch = convert_border_hole_to_notch(outer, hole)
        self.assertIsNotNone(notch)
        assert notch is not None
        self.assertAlmostEqual(_area(notch), 10000.0 - 100.0, places=6)
        # 缺口应深入材料到 x=10，且没有任何点越过板边。
        ring = _ring(notch)
        self.assertTrue(any(abs(point[0] - 10.0) < 1e-6 for point in ring))
        self.assertTrue(all(point[0] >= -1e-9 for point in ring))

    def test_notch_grows_with_extra(self) -> None:
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 40.0, 10.0, 50.0, kind="RELIEF")
        notch = convert_border_hole_to_notch(outer, hole, grow=1.0)
        self.assertIsNotNone(notch)
        assert notch is not None
        # 深 10+1=11，宽 10+1（沿边两侧各 0.5）→ 121。
        self.assertAlmostEqual(_area(notch), 10000.0 - 121.0, places=6)

    def test_interior_hole_not_converted(self) -> None:
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(40.0, 40.0, 50.0, 50.0, kind="RELIEF")
        self.assertIsNone(convert_border_hole_to_notch(outer, hole))

    def test_expansion_converts_border_hole_and_drops_it(self) -> None:
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 40.0, 10.0, 50.0, kind="RELIEF")
        profile, holes, changed = apply_rectangular_relief_expansion(
            outer,
            ((hole, tuple(_ring(hole))),),
            1,
            (),
        )
        self.assertEqual(changed, 1)
        self.assertEqual(holes, ())
        self.assertAlmostEqual(_area(profile), 10000.0 - 121.0, places=6)

    def test_partial_edge_touch_is_kept_as_hole(self) -> None:
        # L 形板：x=0 边只到 y=40。孔一半贴边（y 30..40）、一半悬空
        # （y 40..50 没有板边可贴）→ 转缺口会切不干净，保持为孔。
        ring = [
            (0.0, 0.0),
            (100.0, 0.0),
            (100.0, 100.0),
            (40.0, 100.0),
            (40.0, 40.0),
            (0.0, 40.0),
        ]
        segments = tuple(
            SketchSegment(start, end)
            for start, end in zip(ring, ring[1:] + [ring[0]])
        )
        outer = Primitive(
            tuple(ring) + ((0.0, 0.0),),
            True,
            False,
            "0",
            "LINE_LOOP",
            segments,
        )
        hole = _rect(0.0, 30.0, 10.0, 50.0, kind="RELIEF")
        self.assertIsNone(convert_border_hole_to_notch(outer, hole))


class NearBorderIntersectionTests(unittest.TestCase):
    def test_intersection_near_border_cuts_notch(self) -> None:
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        vertical = _bend((99.0, 10.0), (99.0, 60.0))
        horizontal = _bend((0.0, 45.0), (100.0, 45.0))
        profile, holes, added = ensure_intersection_reliefs(
            outer,
            (),
            (vertical, horizontal),
            2.0,
            1.0,
            relief_step=1,
        )
        self.assertEqual(added, 0)
        self.assertEqual(holes, ())
        # 缺口从右边界 x=100 伸到 x=98，宽 1 → 面积少 2。
        self.assertAlmostEqual(_area(profile), 10000.0 - 2.0, places=6)
        ring = _ring(profile)
        self.assertTrue(any(abs(point[0] - 98.0) < 1e-6 for point in ring))

    def test_intersection_in_panel_interior_still_adds_hole(self) -> None:
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        vertical = _bend((50.0, 10.0), (50.0, 60.0))
        horizontal = _bend((0.0, 45.0), (100.0, 45.0))
        profile, holes, added = ensure_intersection_reliefs(
            outer,
            (),
            (vertical, horizontal),
            2.0,
            1.0,
            relief_step=1,
        )
        self.assertEqual(added, 1)
        self.assertEqual(len(holes), 1)
        self.assertEqual(_area(profile), 10000.0)


class NotchDirectionTests(unittest.TestCase):
    def test_border_notch_deepens_toward_panel(self) -> None:
        # 已是外轮廓缺口的槽（左边缘 x=0 开口、底在 x=5），
        # 扩槽朝材料内加深：缺口底从 x=5 推到 x=6。
        r = 5.0
        ring = [
            (r, 0.0),
            (100.0, 0.0),
            (100.0, 100.0),
            (r, 100.0),
            (r, 95.0),
            (0.0, 95.0),
            (0.0, 5.0),
            (r, 5.0),
        ]
        segments = tuple(
            SketchSegment(start, end)
            for start, end in zip(ring, ring[1:] + [ring[0]])
        )
        outer = Primitive(
            tuple(ring) + ((r, 0.0),),
            True,
            False,
            "0",
            "LINE_LOOP",
            segments,
        )
        grown = expand_rectangular_relief_notches(outer, 1.0)
        xs = [point[0] for point in _ring(grown)]
        self.assertTrue(any(abs(x - 6.0) < 1e-6 for x in xs))


if __name__ == "__main__":
    unittest.main()


class NearBorderHoleTests(unittest.TestCase):
    def test_gap_to_border_is_stretched_into_notch(self) -> None:
        # 孔离板边 0.5mm 细缝 → 拉伸到边后开缺口，不留悬空窄条。
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.5, 40.0, 10.0, 50.0, kind="RELIEF")
        notch = convert_border_hole_to_notch(outer, hole, grow=1.0)
        self.assertIsNotNone(notch)
        assert notch is not None
        ring = _ring(notch)
        self.assertTrue(all(point[0] >= -1e-9 for point in ring))
        # 深度从孔远边 10 算 +1 → x=11 的底。
        self.assertTrue(any(abs(point[0] - 11.0) < 1e-6 for point in ring))
        xs = [point[0] for point in ring]
        self.assertAlmostEqual(min(xs), 0.0, places=6)
