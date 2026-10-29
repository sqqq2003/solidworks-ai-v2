"""Offline unit tests for the bend-geometry helpers that had no coverage.

These pure functions are the exact terrain where p248 kept tripping:
bend/profile intersections, fixed-panel anchor selection, and the
parallel/collinear bend-axis checks. They are deterministic and need no
SolidWorks, so they can be locked down offline. Cloud pass != machine pass;
these tests only pin the offline geometry contract, they do not claim any
machine acceptance.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import math
import unittest

from cad_analyzer import Primitive, SketchSegment
import solidworks_generator as sw


def polygon(points):
    ring = tuple(points) + (points[0],)
    return Primitive(ring, True, False, 'synthetic', 'LINE_LOOP',
                     tuple(SketchSegment(a, b) for a, b in zip(ring, ring[1:])))


def bend(points):
    """A synthetic bend mark (finite annotation), not a loop."""
    return Primitive(tuple(points), False, True, 'synthetic', 'LINE')


class BendProfileIntersectionTests(unittest.TestCase):
    def setUp(self):
        # 100x80 rectangle profile.
        self.profile = polygon(((0, 0), (100, 0), (100, 80), (0, 80)))

    def test_horizontal_bend_crossing_left_and_right_edges(self):
        b = bend(((0, 40), (100, 40)))
        hits = sw._bend_profile_intersections(b, self.profile)
        self.assertEqual(len(hits), 2)
        self.assertIn((0.0, 40.0), hits)
        self.assertIn((100.0, 40.0), hits)

    def test_vertical_bend_crossing_top_and_bottom_edges(self):
        b = bend(((50, 0), (50, 80)))
        hits = sw._bend_profile_intersections(b, self.profile)
        self.assertEqual(len(hits), 2)
        self.assertIn((50.0, 0.0), hits)
        self.assertIn((50.0, 80.0), hits)

    def test_bend_fully_inside_profile_has_no_intersection(self):
        # A short mark floating inside the material does not touch the outline.
        b = bend(((40, 40), (60, 40)))
        self.assertEqual(sw._bend_profile_intersections(b, self.profile), ())

    def test_bend_outside_profile_has_no_intersection(self):
        b = bend(((-10, 40), (-5, 40)))
        self.assertEqual(sw._bend_profile_intersections(b, self.profile), ())

    def test_bend_ending_exactly_on_an_edge(self):
        b = bend(((0, 40), (100, 40)))
        hits = sw._bend_profile_intersections(b, self.profile)
        self.assertEqual(len(hits), 2)


class BendOutlineEndsTests(unittest.TestCase):
    def setUp(self):
        self.profile = polygon(((0, 0), (100, 0), (100, 80), (0, 80)))

    def test_direct_crossing_uses_the_intersections(self):
        b = bend(((0, 40), (100, 40)))
        ends = sw._bend_outline_ends(b, self.profile)
        self.assertEqual(len(ends), 2)
        self.assertIn((0.0, 40.0), ends)
        self.assertIn((100.0, 40.0), ends)

    def test_short_internal_mark_is_extended_to_both_edges(self):
        # A short mark floating inside is extended along its direction.
        b = bend(((40, 40), (60, 40)))
        ends = sw._bend_outline_ends(b, self.profile)
        self.assertEqual(len(ends), 2)
        self.assertIn((0.0, 40.0), ends)
        self.assertIn((100.0, 40.0), ends)

    def test_zero_length_bend_returns_empty(self):
        b = bend(((50, 40), (50, 40)))
        self.assertEqual(sw._bend_outline_ends(b, self.profile), ())


class BendFeatureOutlineSpanTests(unittest.TestCase):
    def setUp(self):
        self.profile = polygon(((0, 0), (100, 0), (100, 80), (0, 80)))

    def test_full_span_across_profile(self):
        b = bend(((0, 40), (100, 40)))
        span = sw._bend_feature_outline_span(b, self.profile)
        self.assertIsNotNone(span)
        a, c = span
        self.assertEqual(a, (0.0, 40.0))
        self.assertEqual(c, (100.0, 40.0))

    def test_partial_mark_still_yields_full_span(self):
        # Even a mark touching only one edge resolves the full crossing span.
        b = bend(((0, 40), (50, 40)))
        span = sw._bend_feature_outline_span(b, self.profile)
        self.assertIsNotNone(span)
        self.assertEqual(span[0], (0.0, 40.0))
        self.assertEqual(span[1], (100.0, 40.0))

    def test_zero_length_bend_yields_none(self):
        b = bend(((50, 40), (50, 40)))
        self.assertIsNone(sw._bend_feature_outline_span(b, self.profile))


class BendAxisRelationTests(unittest.TestCase):
    def test_parallel_bends(self):
        a = bend(((0, 20), (100, 20)))
        b = bend(((0, 60), (100, 60)))
        self.assertTrue(sw._bends_are_roughly_parallel(a, b))

    def test_perpendicular_bends_are_not_parallel(self):
        a = bend(((0, 40), (100, 40)))
        b = bend(((50, 0), (50, 80)))
        self.assertFalse(sw._bends_are_roughly_parallel(a, b))

    def test_angle_tolerance_boundary(self):
        a = bend(((0, 0), (100, 0)))
        b = bend(((0, 0), (100, 10)))  # ~5.7 degrees
        self.assertTrue(sw._bends_are_roughly_parallel(a, b, angle_tol_deg=6.0))
        self.assertFalse(sw._bends_are_roughly_parallel(a, b, angle_tol_deg=3.0))

    def test_zero_length_bend_is_not_parallel(self):
        a = bend(((0, 0), (0, 0)))
        b = bend(((0, 20), (100, 20)))
        self.assertFalse(sw._bends_are_roughly_parallel(a, b))

    def test_collinear_bends_on_the_same_line(self):
        a = bend(((0, 40), (40, 40)))
        b = bend(((60, 40), (100, 40)))
        self.assertTrue(sw._bends_are_collinear(a, b))

    def test_offset_parallel_bends_are_not_collinear(self):
        a = bend(((0, 20), (100, 20)))
        b = bend(((0, 60), (100, 60)))
        self.assertFalse(sw._bends_are_collinear(a, b))

    def test_collinear_but_within_distance_tolerance(self):
        a = bend(((0, 40), (40, 40)))
        b = bend(((60, 40.4), (100, 40.4)))  # 0.4mm offset
        self.assertTrue(sw._bends_are_collinear(a, b, distance_tol_mm=1.0))
        self.assertFalse(sw._bends_are_collinear(a, b, distance_tol_mm=0.1))


class FixedPanelAnchorTests(unittest.TestCase):
    def setUp(self):
        self.outer = polygon(((0, 0), (100, 0), (100, 80), (0, 80)))
        # Two horizontal + two vertical bends define a central cell.
        self.bends = tuple(bend(p) for p in (
            ((35, 20), (65, 20)), ((35, 60), (65, 60)),
            ((20, 28), (20, 52)), ((80, 52), (80, 28))))

    def test_best_fixed_face_point_lands_in_central_material(self):
        point = sw._best_fixed_face_point(self.outer, self.bends)
        self.assertTrue(20 < point[0] < 80, point)
        self.assertTrue(20 < point[1] < 60, point)
        self.assertTrue(sw._point_in_profile(point, self.outer))

    def test_explicit_anchor_is_authoritative(self):
        anchor = (50.0, 40.0)
        candidates = sw._fixed_face_pick_candidates(self.outer, self.bends, preferred=anchor)
        self.assertEqual(candidates, [anchor])

    def test_explicit_anchor_on_a_bend_axis_is_rejected(self):
        with self.assertRaises(ValueError):
            sw._fixed_face_pick_candidates(self.outer, self.bends, preferred=(50.0, 20.0))

    def test_explicit_anchor_outside_material_is_rejected(self):
        with self.assertRaises(ValueError):
            sw._fixed_face_pick_candidates(self.outer, self.bends, preferred=(120.0, 40.0))

    def test_zero_length_bend_rejects_anchor_selection(self):
        bad = (self.bends[0], bend(((0, 0), (0, 0))))
        with self.assertRaises(ValueError):
            sw._best_fixed_face_point(self.outer, bad)

    def test_nonconvex_profile_still_finds_a_material_point(self):
        # L-shaped profile whose bbox centre is outside material.
        lshape = polygon(((0, 0), (100, 0), (100, 30), (30, 30), (30, 80), (0, 80)))
        b = (bend(((0, 40), (30, 40))),)
        point = sw._best_fixed_face_point(lshape, b)
        self.assertTrue(sw._point_in_profile(point, lshape))


if __name__ == '__main__':
    unittest.main()
