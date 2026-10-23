# -*- coding: utf-8 -*-
"""Reconstruction guards: artifact-loop predicate and border-hole notch.

The promoted snapshot tests pin the documented cases; these pin the edges the
rebuild had to decide on its own (ring orientation, mouth clamping, size gate,
2 mm border threshold), so a later change cannot silently widen or narrow them.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import math
import unittest

from cad_analyzer import Primitive, SketchSegment
from solidworks_generator import (
    _is_drawing_artifact_loop,
    apply_rectangular_relief_expansion,
    convert_border_hole_to_notch,
    ensure_intersection_reliefs,
)


def _rect(min_x, min_y, max_x, max_y, *, clockwise=False, kind="LINE_LOOP"):
    ring = [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]
    if clockwise:
        ring = [ring[0], ring[3], ring[2], ring[1]]
    closed = ring + [ring[0]]
    segments = tuple(
        SketchSegment(start, end) for start, end in zip(closed, closed[1:])
    )
    return Primitive(tuple(closed), True, False, "0", kind, segments)


def _bend(start, end):
    return Primitive(
        (start, end), False, True, "折弯线", "LINE", (SketchSegment(start, end),)
    )


def _ring(profile):
    points = list(profile.points)
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points


def _area(profile):
    ring = _ring(profile)
    total = 0.0
    for index in range(len(ring)):
        x1, y1 = ring[index]
        x2, y2 = ring[(index + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


class NotchOrientationTests(unittest.TestCase):
    def test_clockwise_outer_ring_still_cuts_inward(self):
        outer = _rect(0.0, 0.0, 100.0, 100.0, clockwise=True)
        hole = _rect(0.0, 40.0, 10.0, 50.0, kind="RELIEF")
        notch = convert_border_hole_to_notch(outer, hole)
        self.assertIsNotNone(notch)
        assert notch is not None
        self.assertAlmostEqual(_area(notch), 10000.0 - 100.0, places=6)
        ring = _ring(notch)
        self.assertTrue(any(abs(point[0] - 10.0) < 1e-6 for point in ring))
        self.assertTrue(all(point[0] >= -1e-9 for point in ring))

    def test_notch_ring_stays_closed_and_connected(self):
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 40.0, 10.0, 50.0, kind="RELIEF")
        notch = convert_border_hole_to_notch(outer, hole, grow=1.0)
        assert notch is not None
        ring = list(notch.points)
        self.assertEqual(ring[0], ring[-1])
        for start, end in zip(ring, ring[1:]):
            self.assertGreater(math.dist(start, end), 1e-12)
        self.assertEqual(len(notch.curve_segments), len(ring) - 1)


class NotchClampTests(unittest.TestCase):
    def test_corner_hole_uses_longer_contact_and_clamps_mouth(self):
        # 角部孔同时贴左边（贴合 5 mm）与上边（贴合 10 mm）：缺口开在贴合更长的
        # 上边；grow=2 让口部算到 x=-1，必须 clamp 在板角内，不得推出轮廓。
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 95.0, 10.0, 100.0, kind="RELIEF")
        notch = convert_border_hole_to_notch(outer, hole, grow=2.0)
        self.assertIsNotNone(notch)
        assert notch is not None
        ring = _ring(notch)
        for point in ring:
            self.assertGreaterEqual(point[0], -1e-9)
            self.assertLessEqual(point[0], 100.0 + 1e-9)
            self.assertGreaterEqual(point[1], -1e-9)
            self.assertLessEqual(point[1], 100.0 + 1e-9)
        # 深 5+2=7，口部 clamp 后宽 11 → 少 77。
        self.assertAlmostEqual(_area(notch), 10000.0 - 77.0, places=6)
        self.assertTrue(any(abs(point[1] - 93.0) < 1e-6 for point in ring))
        self.assertTrue(any(abs(point[0] - 11.0) < 1e-6 for point in ring))

    def test_single_edge_hole_is_not_clamped(self):
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 40.0, 10.0, 50.0, kind="RELIEF")
        notch = convert_border_hole_to_notch(outer, hole, grow=2.0)
        assert notch is not None
        # 深 12、宽 12 → 少 144；口部远离边端点，clamp 不参与。
        self.assertAlmostEqual(_area(notch), 10000.0 - 144.0, places=6)


class SizeGateTests(unittest.TestCase):
    def test_large_border_opening_stays_a_hole(self):
        # 60×60 的贴边开口不是释放槽孔，不能被转成缺口。
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 20.0, 60.0, 80.0, kind="RELIEF")
        profile, holes, changed = apply_rectangular_relief_expansion(
            outer, ((hole, tuple(_ring(hole))),), 1, ()
        )
        self.assertEqual(len(holes), 1)
        self.assertEqual(changed, 0)
        self.assertAlmostEqual(_area(profile), 10000.0, places=6)

    def test_direct_call_still_converts_when_asked(self):
        # 尺寸闸门在扩槽路径上；直接调用仍按几何判断。
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 20.0, 60.0, 80.0, kind="RELIEF")
        self.assertIsNotNone(convert_border_hole_to_notch(outer, hole))


class BorderDistanceThresholdTests(unittest.TestCase):
    def test_intersection_beyond_two_mm_still_adds_hole(self):
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        vertical = _bend((97.0, 10.0), (97.0, 60.0))
        horizontal = _bend((0.0, 45.0), (100.0, 45.0))
        profile, holes, added = ensure_intersection_reliefs(
            outer, (), (vertical, horizontal), 2.0, 1.0, relief_step=1
        )
        self.assertEqual(added, 1)
        self.assertEqual(len(holes), 1)
        self.assertAlmostEqual(_area(profile), 10000.0, places=6)

    def test_negative_grow_is_refused(self):
        outer = _rect(0.0, 0.0, 100.0, 100.0)
        hole = _rect(0.0, 40.0, 10.0, 50.0, kind="RELIEF")
        with self.assertRaises(ValueError):
            convert_border_hole_to_notch(outer, hole, grow=-1.0)


class ArtifactPredicateEdgeTests(unittest.TestCase):
    def test_open_or_degenerate_loops_are_not_artifacts(self):
        open_line = Primitive(
            ((0.0, 0.0), (1.0, 0.0)), False, False, "0", "LINE",
            (SketchSegment((0.0, 0.0), (1.0, 0.0)),),
        )
        self.assertFalse(_is_drawing_artifact_loop(open_line))
        two_point = Primitive(((0.0, 0.0), (1.0, 0.0)), True, False, "0", "LINE_LOOP")
        self.assertFalse(_is_drawing_artifact_loop(two_point))

    def test_long_thin_residue_is_not_an_artifact_loop(self):
        # 面积 0.05 mm² 但最长边 50 mm：判定是「最大边 ≤2 且面积 ≤0.6」，两者都要满足。
        sliver = Primitive(
            ((0.0, 0.0), (50.0, 0.0), (50.0, 0.001), (0.0, 0.001), (0.0, 0.0)),
            True, False, "0", "LINE_LOOP",
        )
        self.assertFalse(_is_drawing_artifact_loop(sliver))

    def test_tiny_circle_counts_as_artifact(self):
        # Φ0.5 面积 0.196 mm²、最大边远小于 2 mm：按标注残留处理（规格如此）。
        points = tuple(
            (math.cos(math.radians(step * 15)) * 0.25, math.sin(math.radians(step * 15)) * 0.25)
            for step in range(24)
        )
        hole = Primitive(points, True, False, "0", "CIRCLE")
        self.assertTrue(_is_drawing_artifact_loop(hole))


if __name__ == "__main__":
    unittest.main()
