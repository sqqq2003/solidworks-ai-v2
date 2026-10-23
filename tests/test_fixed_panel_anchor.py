"""Synthetic short bend marks must not move the fixed panel between groups."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import math
import unittest
from unittest.mock import MagicMock, patch
from cad_analyzer import DrawingAnalysis, Primitive, SketchSegment
import solidworks_generator as sw


def polygon(points):
    ring = tuple(points) + (points[0],)
    return Primitive(ring, True, False, 'synthetic', 'LINE_LOOP',
                     tuple(SketchSegment(a, b) for a, b in zip(ring, ring[1:])))


class FixedPanelAnchorTests(unittest.TestCase):
    def setUp(self):
        self.outer = polygon(((0, 0), (100, 0), (100, 80), (0, 80)))
        self.bends = tuple(Primitive(points, False, True, 'synthetic', 'LINE') for points in (
            ((35, 20), (65, 20)), ((35, 60), (65, 60)),
            ((20, 28), (20, 52)), ((80, 52), (80, 28))))
        self.hole = polygon(((44, 34), (56, 34), (56, 46), (44, 46)))

    def test_short_marks_prioritize_the_common_central_panel(self):
        point = sw._fixed_face_pick_candidates(self.outer, self.bends)[0]
        self.assertTrue(20 < point[0] < 80 and 20 < point[1] < 60, point)

    def test_hole_is_excluded_from_fixed_panel_candidates(self):
        candidates = sw._fixed_face_pick_candidates(self.outer, self.bends, holes=(self.hole,))
        self.assertTrue(candidates)
        self.assertTrue(all(not sw._point_in_profile(point, self.hole) for point in candidates))
        self.assertTrue(all(20 < x < 80 and 20 < y < 60 for x, y in candidates))

    def test_explicit_fixed_point_inside_a_hole_is_rejected(self):
        with self.assertRaises(ValueError):
            sw._fixed_face_pick_candidates(self.outer, self.bends, preferred=(50, 40), holes=(self.hole,))

    def test_all_parallel_groups_share_one_unchanged_anchor(self):
        analysis = DrawingAnalysis(Path('synthetic.dxf'), 'mm', (), self.bends,
                                   (self.outer, self.hole), (0, 0, 100, 80), 'Model')
        anchors = []
        def create(*args, **kwargs):
            anchors.append(args[13])
            if len(args[7]) == 4:
                raise sw.BendRejectedError(args[7], relief_step=0)
        with patch.object(sw, '_create_bend_feature', side_effect=create):
            count = sw._create_bends_with_fallbacks(
                *[MagicMock() for _ in range(6)], analysis, (0, 1, 2, 3),
                (0, 0), 2.5, 1, 90, False, None, 0, None, self.outer,
                hole_profiles=(self.hole,))
        self.assertEqual(count, 4)
        self.assertGreaterEqual(len(anchors), 3)
        self.assertTrue(all(anchor == anchors[0] for anchor in anchors))
        self.assertIsNotNone(anchors[0])
        self.assertFalse(sw._point_in_profile(anchors[0], self.hole))

    def test_reversed_bend_directions_select_the_same_panel(self):
        reverse = tuple(Primitive(tuple(reversed(b.points)), False, True, b.layer, b.kind)
                        for b in self.bends)
        self.assertEqual(sw._fixed_face_pick_candidates(self.outer, self.bends)[0],
                         sw._fixed_face_pick_candidates(self.outer, reverse)[0])

    def test_group_diagnostics_survive_rejection(self):
        analysis = DrawingAnalysis(Path('synthetic.dxf'), 'mm', (), self.bends,
                                   (self.outer, self.hole), (0, 0, 100, 80), 'Model')
        events = []
        def reject(*args, **kwargs):
            raise sw.BendRejectedError(args[7])
        with patch.object(sw, '_create_bend_feature', side_effect=reject):
            with self.assertRaises(sw.BendRejectedError) as caught:
                sw._create_bends_with_fallbacks(
                    *[MagicMock() for _ in range(6)], analysis, (0, 1, 2, 3),
                    (0, 0), 2.5, 1, 90, False, None, 0, None, self.outer,
                    hole_profiles=(self.hole,), group_attempts=events)
        self.assertEqual(len(events), 7)  # all, two groups, four single bends
        self.assertEqual(caught.exception.bend_group_attempts, tuple(events))
        self.assertEqual([e['sequence'] for e in events], list(range(1, 8)))
        self.assertTrue(all(e['status'] == 'failed' for e in events))
        self.assertTrue(all(e['error_kind'] == 'BendRejectedError' for e in events))
        self.assertTrue(all(e['fixed_point_mm'] == events[0]['fixed_point_mm'] for e in events))
        self.assertTrue(all(e['elapsed_seconds'] >= 0 for e in events))

    def test_group_diagnostics_record_success_without_claiming_acceptance(self):
        analysis = DrawingAnalysis(Path('synthetic.dxf'), 'mm', (), self.bends,
                                   (self.outer,), (0, 0, 100, 80), 'Model')
        events = []
        with patch.object(sw, '_create_bend_feature'):
            count = sw._create_bends_with_fallbacks(
                *[MagicMock() for _ in range(6)], analysis, (0, 1, 2, 3),
                (0, 0), 2.5, 1, 90, False, None, 0, None, self.outer,
                group_attempts=events)
        self.assertEqual(count, 4)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['status'], 'created')
        self.assertEqual(events[0]['scope'], 'feature_creation_not_native_acceptance')
        self.assertEqual(events[0]['index_base'], 0)
