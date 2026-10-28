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
        observed = [0]
        def create(*args, **kwargs):
            anchors.append(args[13])
            if len(args[7]) == 4:
                raise sw.BendRejectedError(args[7], relief_step=0)
            observed[0] += len(args[7])
        with patch.object(sw, '_create_bend_feature', side_effect=create), patch.object(
                sw, '_count_bend_features', side_effect=lambda *_: observed[0]):
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
        with patch.object(sw, '_create_bend_feature', side_effect=reject), patch.object(sw, '_count_bend_features', return_value=0):
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
        observed = [0]
        def create(*args, **kwargs):
            observed[0] += len(args[7])
        with patch.object(sw, '_create_bend_feature', side_effect=create), patch.object(
                sw, '_count_bend_features', side_effect=lambda *_: observed[0]):
            count = sw._create_bends_with_fallbacks(
                *[MagicMock() for _ in range(6)], analysis, (0, 1, 2, 3),
                (0, 0), 2.5, 1, 90, False, None, 0, None, self.outer,
                group_attempts=events)
        self.assertEqual(count, 4)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['status'], 'created')
        self.assertEqual(events[0]['scope'], 'feature_creation_not_native_acceptance')
        self.assertEqual(events[0]['index_base'], 0)

    def test_fixed_panel_face_survives_larger_folded_wings(self):
        from types import SimpleNamespace
        # Area order is two folded wings first, then the unchanged central skins.
        wing = SimpleNamespace(GetBox=lambda: (0, 0, 0, .1, 0, .08))
        top = SimpleNamespace(GetBox=lambda: (0, 0, 0, .1, .08, 0),
                              GetSurface=lambda: SimpleNamespace(IsPlane=lambda: True, PlaneParams=(0,0,1,0,0,0)),
                              GetClosestPointOn=lambda x,y,z: (x,y,z,0,0))
        bottom = SimpleNamespace(GetBox=lambda: (0, 0, -.0025, .1, .08, -.0025),
                                 GetSurface=lambda: SimpleNamespace(IsPlane=lambda:True, PlaneParams=(0,0,-1,0,0,-.0025)),
                                 GetClosestPointOn=top.GetClosestPointOn)
        candidates = sw._fixed_panel_faces([wing, wing, top, bottom], (50, 40), (0, 0), 2.5)
        self.assertEqual(candidates, [top, bottom])

    def test_face_bbox_alone_does_not_prove_anchor_membership(self):
        from types import SimpleNamespace
        face = SimpleNamespace(GetBox=lambda: (0, 0, 0, .1, .08, 0),
                               GetSurface=lambda: SimpleNamespace(IsPlane=lambda: True, PlaneParams=(0,0,1,0,0,0)),
                               GetClosestPointOn=lambda x,y,z: (x+.005,y,z,0,0))
        self.assertEqual(sw._fixed_panel_faces([face], (50, 40), (0, 0), 2.5), [])

    def test_unavailable_face_geometry_fails_closed(self):
        from types import SimpleNamespace
        face = SimpleNamespace(GetBox=lambda: (0, 0, 0, .1, .08, 0))
        self.assertEqual(sw._fixed_panel_faces([face], (50,40), (0,0), 2.5), [])

    def test_feature_scheduler_uses_central_face_even_when_area_rank_is_third(self):
        from types import SimpleNamespace
        wing = SimpleNamespace(GetBox=lambda:(0,0,0,.1,0,.08))
        central = SimpleNamespace(GetBox=lambda:(0,0,0,.1,.08,0),
            GetSurface=lambda:SimpleNamespace(IsPlane=lambda:True, PlaneParams=(0,0,1,0,0,0)),
            GetClosestPointOn=lambda x,y,z:(x,y,z,0,0))
        analysis = SimpleNamespace(profiles=(self.outer,), bend_lines=self.bends)
        sketch = SimpleNamespace(Name='synthetic-bend')
        with patch.object(sw, '_as_interface', side_effect=lambda module,obj,name:obj), \
             patch.object(sw, '_planar_faces_by_area', return_value=[wing,wing,central]), \
             patch.object(sw, '_create_bend_sketch_on_face', return_value=(sketch,None)) as create, \
             patch.object(sw, '_try_insert_sheet_metal_bend', return_value=True), \
             patch.object(sw, '_build_custom_bend_allowance', return_value=None), \
             patch.object(sw, '_auto_bend_deadline', None):
            sw._create_bend_feature(*[MagicMock() for _ in range(6)], analysis,
                (2,3), (0,0), 2.5, 1, 90, False, fixed_face_point=(50,40),
                outer_profile=self.outer)
        self.assertIs(create.call_args.args[9], central)

    def test_approximate_bbox_cannot_reject_exact_fixed_plane(self):
        from types import SimpleNamespace
        # SW documents GetBox as approximate, even for a planar face.
        face = SimpleNamespace(GetBox=lambda: (-.001,-.001,-.0001,.101,.081,.0001),
            GetSurface=lambda:SimpleNamespace(IsPlane=lambda:True, PlaneParams=(0,0,1,0,0,0)),
            GetClosestPointOn=lambda x,y,z:(x,y,z,0,0))
        self.assertEqual(sw._fixed_panel_faces([face], (50,40), (0,0), 2.5), [face])

    def test_dynamic_com_property_plane_is_supported(self):
        from types import SimpleNamespace
        # Late-bound COM can return zero-argument members as property values.
        face = SimpleNamespace(GetSurface=SimpleNamespace(IsPlane=True,
            PlaneParams=(0,0,-1,0,0,-.0025)),
            GetClosestPointOn=lambda x,y,z:(x,y,z,0,0))
        self.assertEqual(sw._fixed_panel_faces([face], (50,40), (0,0), 2.5), [face])
        self.assertEqual(sw._fixed_panel_plane_z(face), -.0025)

    def test_exact_plane_normal_rejects_folded_face_even_with_flat_bbox(self):
        from types import SimpleNamespace
        face = SimpleNamespace(GetBox=lambda:(0,0,0,.1,.08,0),
            GetSurface=lambda:SimpleNamespace(IsPlane=lambda:True, PlaneParams=(0,1,0,0,0,0)),
            GetClosestPointOn=lambda x,y,z:(x,y,z,0,0))
        self.assertEqual(sw._fixed_panel_faces([face], (50,40), (0,0), 2.5), [])
