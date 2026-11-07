import copy
import json
from pathlib import Path
import unittest

from engineering_intelligence import run_module
from engineering_intelligence.common import review_digest
from engineering_intelligence.mate_rank import MAX_MOVING_COMPONENTS, analyse_constraints
from ql5050px.assembly import inspect_assembly

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'synthetic test geometry'


def example():
    return json.loads((ROOT/'examples/issue50-assembly.json').read_text(encoding='utf-8'))


def axis(point, direction): return {'kind': 'axis', 'point_mm': list(point), 'direction': list(direction)}
def plane(point, normal): return {'kind': 'plane', 'point_mm': list(point), 'normal': list(normal)}
def point(p): return {'kind': 'point', 'point_mm': list(p)}


def mate(mate_id, a, b, kind, ea, eb, **extra):
    return {'id': mate_id, 'a': a, 'b': b, 'type': kind,
            'geometry': dict({'unit': 'mm', 'source': SOURCE, 'a': ea, 'b': eb}, **extra)}


def revolute(name, a, b, centre):
    return [mate(name+'_axis', a, b, 'concentric', axis(centre, (0, 0, 1)), axis(centre, (0, 0, 1))),
            mate(name+'_face', a, b, 'coincident', plane(centre, (0, 0, 1)), plane(centre, (0, 0, -1)))]


def component(report, name):
    return next(row for row in report['constraint_rank']['components'] if row['id'] == name)


class RollerExampleTests(unittest.TestCase):
    def test_roller_only_spins_about_its_axis(self):
        report = run_module('assembly', example())
        rank = report['constraint_rank']
        self.assertEqual(rank['mobility'], 1)
        roller = component(report, 'roller')
        self.assertEqual(roller['translations'], [])
        self.assertEqual(roller['rotations'], [{'direction': [1.0, 0.0, 0.0], 'axis_point_mm': [0.0, 0.0, 0.0], 'pitch_mm_per_rad': 0.0}])
        self.assertEqual(report['issues'], ['native_readback_not_run'])
        self.assertEqual(report['status'], 'review_required')
        self.assertFalse(report['engineering_approved'])

    def test_concentric_and_face_overlap_is_not_reported_as_redundant(self):
        rank = run_module('assembly', example())['constraint_rank']
        self.assertEqual(rank['pair_redundant_equations'], 2)
        self.assertEqual(rank['loop_redundant_equations'], 0)
        self.assertFalse(any(row['removable_within_pair'] for row in rank['mates']))

    def test_two_bearings_without_axial_stop_still_slide(self):
        request = example()
        request['mates'][1] = mate('second_bearing', 'frame', 'roller', 'concentric',
                                   axis((800, 0, 0), (1, 0, 0)), axis((790, 0, 0), (1, 0, 0)))
        report = run_module('assembly', request)
        # The scalar table counts 4+4 removed DOF and calls the roller fully fixed.
        self.assertEqual(report['offline']['estimated_dof']['roller'], 0)
        roller = component(report, 'roller')
        self.assertEqual(roller['dof'], 2)
        self.assertEqual(roller['translations'], [[1.0, 0.0, 0.0]])
        self.assertEqual(report['status'], 'failed')
        self.assertIn('constraint_dof_mismatch:roller', report['failures'])
        self.assertIn('unexpected_free_motion:roller', report['failures'])
        self.assertIn('redundant_mates:__ground__/roller:concentric,second_bearing', report['issues'])

    def test_exact_duplicate_mate_is_removable(self):
        request = example()
        duplicate = copy.deepcopy(request['mates'][0]); duplicate['id'] = 'again'
        request['mates'].append(duplicate)
        rank = run_module('assembly', request)['constraint_rank']
        flags = {row['id']: row['removable_within_pair'] for row in rank['mates']}
        self.assertEqual(flags, {'concentric': True, 'axial': False, 'again': True})
        self.assertEqual(rank['mobility'], 1)

    def test_offset_axis_is_an_unsatisfied_mate(self):
        request = example()
        request['mates'][0]['geometry']['b']['point_mm'] = [400, 0.5, 0]
        report = run_module('assembly', request)
        self.assertIn('mate_geometry_unsatisfied:concentric', report['failures'])
        residual = next(r for r in report['constraint_rank']['mates'] if r['id'] == 'concentric')['residual']
        self.assertAlmostEqual(residual['linear_mm'], 0.5)

    def test_linear_tolerance_is_explicit(self):
        request = example()
        request['mates'][0]['geometry']['b']['point_mm'] = [400, 0.5, 0]
        request['linear_tolerance_mm'] = 1.0
        report = run_module('assembly', request)
        self.assertNotIn('mate_geometry_unsatisfied:concentric', report['failures'])
        self.assertEqual(report['constraint_rank']['tolerances']['linear_mm'], 1.0)

    def test_wrong_axial_distance_is_unsatisfied(self):
        request = example()
        request['mates'][1]['geometry']['distance']['value'] = 8
        self.assertIn('mate_geometry_unsatisfied:axial', run_module('assembly', request)['failures'])

    def test_blocked_expected_motion_fails(self):
        request = example()
        request['components'][1]['expected_motions'].append({'type': 'translation', 'direction': [1, 0, 0]})
        report = run_module('assembly', request)
        self.assertIn('expected_motion_blocked:roller', report['failures'])
        self.assertEqual(component(report, 'roller')['expected_motions_blocked'], [1])

    def test_rigidly_attached_part_inherits_motion(self):
        request = example()
        request['components'].append({'id': 'sprocket', 'expected_dof': 1})
        request['mates'].append({'id': 'keyed', 'a': 'roller', 'b': 'sprocket', 'type': 'fixed'})
        report = run_module('assembly', request)
        self.assertEqual(report['constraint_rank']['mobility'], 1)
        self.assertEqual(component(report, 'sprocket')['rotations'], component(report, 'roller')['rotations'])
        self.assertEqual(report['failures'], [])

    def test_geometry_change_makes_native_readback_stale(self):
        request = example()
        request['native_readback'] = {'assembly_sha256': review_digest({'components': request['components'], 'mates': request['mates']}),
                                      'scope': 'windows_solidworks', 'source': 'synthetic'}
        self.assertNotIn('stale_native_readback', run_module('assembly', request)['failures'])
        request['mates'][1]['geometry']['distance']['value'] = 6
        request['mates'][1]['geometry']['b']['point_mm'] = [6, 0, 40]
        self.assertIn('stale_native_readback', run_module('assembly', request)['failures'])


class MechanismTests(unittest.TestCase):
    def test_planar_four_bar_has_one_mobility_and_three_loop_redundancies(self):
        ground, crank, coupler, rocker = (0, 0, 0), (20, 34.641016, 0), (90, 60, 0), (100, 0, 0)
        components = [{'id': 'ground', 'fixed': True}, {'id': 'crank'}, {'id': 'coupler'}, {'id': 'rocker'}]
        mates = (revolute('A', 'ground', 'crank', ground) + revolute('B', 'crank', 'coupler', crank)
                 + revolute('C', 'coupler', 'rocker', coupler) + revolute('D', 'rocker', 'ground', rocker))
        report = run_module('assembly', {'components': components, 'mates': mates})
        rank = report['constraint_rank']
        self.assertEqual(rank['mobility'], 1)
        self.assertEqual(rank['loop_redundant_equations'], 3)
        self.assertEqual(rank['pair_redundant_equations'], 8)
        self.assertTrue(any(v.startswith('overconstrained_loop:3:') for v in report['issues']))
        self.assertEqual([component(report, n)['dof'] for n in ('crank', 'coupler', 'rocker')], [1, 1, 1])
        # Coupler's instantaneous centre is where lines AB and DC meet.
        centre = component(report, 'coupler')['rotations'][0]['axis_point_mm']
        self.assertAlmostEqual(centre[0], 77.599, places=2)
        self.assertAlmostEqual(centre[1], 134.405, places=2)
        self.assertEqual(component(report, 'rocker')['rotations'][0]['axis_point_mm'], [100.0, 0.0, 0.0])

    def test_coincident_faces_leave_planar_motion(self):
        components = [{'id': 'table', 'fixed': True}, {'id': 'block'}]
        mates = [mate('rest', 'table', 'block', 'coincident', plane((0, 0, 0), (0, 0, 1)), plane((30, 40, 0), (0, 0, -1)))]
        report = run_module('assembly', {'components': components, 'mates': mates})
        block = component(report, 'block')
        self.assertEqual(block['dof'], 3)
        self.assertEqual(block['translations'], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.assertEqual([r['direction'] for r in block['rotations']], [[0.0, 0.0, 1.0]])
        self.assertIn('free_motion_unreviewed:block', report['issues'])

    def test_rail_slider_keeps_one_translation(self):
        components = [{'id': 'rail', 'fixed': True},
                      {'id': 'carriage', 'expected_dof': 1, 'expected_motions': [{'type': 'translation', 'direction': [1, 0, 0]}]}]
        mates = [mate('seat', 'rail', 'carriage', 'coincident', plane((0, 0, 20), (0, 0, 1)), plane((50, 0, 20), (0, 0, -1))),
                 mate('guide', 'rail', 'carriage', 'coincident', plane((0, 10, 0), (0, 1, 0)), plane((50, 10, 25), (0, -1, 0)))]
        report = run_module('assembly', {'components': components, 'mates': mates})
        self.assertEqual(report['failures'], [])
        self.assertEqual(component(report, 'carriage')['translations'], [[1.0, 0.0, 0.0]])

    def test_perpendicular_and_angle_mates(self):
        components = [{'id': 'base', 'fixed': True}, {'id': 'arm'}]
        hinge = revolute('hinge', 'base', 'arm', (0, 0, 0))
        tilt = mate('tilt', 'base', 'arm', 'angle', plane((0, 0, 0), (1, 0, 0)), plane((0, 0, 0), (0.5, 0.8660254, 0)),
                    angle={'value': 60, 'unit': 'deg', 'source': SOURCE})
        report = run_module('assembly', {'components': components, 'mates': hinge+[tilt]})
        self.assertEqual(component(report, 'arm')['dof'], 0)
        self.assertNotIn('mate_geometry_unsatisfied:tilt', report['failures'])
        square = mate('square', 'base', 'arm', 'perpendicular', plane((0, 0, 0), (1, 0, 0)), plane((0, 0, 0), (0, 1, 0)))
        report = run_module('assembly', {'components': components, 'mates': hinge+[square]})
        self.assertEqual(component(report, 'arm')['dof'], 0)

    def test_point_on_plane_removes_one_freedom(self):
        components = [{'id': 'base', 'fixed': True}, {'id': 'probe'}]
        mates = [mate('touch', 'base', 'probe', 'coincident', point((5, 5, 0)), plane((0, 0, 0), (0, 0, 1)))]
        report = run_module('assembly', {'components': components, 'mates': mates})
        self.assertEqual(component(report, 'probe')['dof'], 5)


class InputBoundaryTests(unittest.TestCase):
    def test_partial_geometry_falls_back_to_scalar_estimate(self):
        request = example(); del request['mates'][1]['geometry']
        report = run_module('assembly', request)
        self.assertIsNone(report['constraint_rank'])
        self.assertIn('constraint_rank_geometry_missing:axial', report['issues'])
        self.assertIn('offline_DOF_is_not_constraint_Jacobian_rank', report['issues'])

    def test_unsupported_mate_type_falls_back(self):
        request = example(); request['mates'][1]['type'] = 'gear'
        report = run_module('assembly', request)
        self.assertIsNone(report['constraint_rank'])
        self.assertIn('constraint_rank_unsupported_mates:axial', report['issues'])

    def test_suppressed_mate_is_ignored(self):
        request = example()
        extra = copy.deepcopy(request['mates'][1]); extra['id'] = 'old'; extra['suppressed'] = True; del extra['geometry']
        request['mates'].append(extra)
        self.assertEqual(run_module('assembly', request)['constraint_rank']['mobility'], 1)

    def test_geometry_needs_unit_and_source(self):
        request = example(); del request['mates'][0]['geometry']['source']
        with self.assertRaises(ValueError): run_module('assembly', request)
        request = example(); request['mates'][0]['geometry']['unit'] = 'm'
        with self.assertRaises(ValueError): run_module('assembly', request)

    def test_distance_needs_explicit_quantity(self):
        request = example(); del request['mates'][1]['geometry']['distance']
        with self.assertRaises(ValueError): run_module('assembly', request)

    def test_wrong_entity_pair_is_rejected(self):
        request = example(); request['mates'][0]['geometry']['a'] = plane((0, 0, 0), (1, 0, 0))
        with self.assertRaises(ValueError): run_module('assembly', request)

    def test_zero_direction_and_bad_numbers_rejected(self):
        request = example(); request['mates'][0]['geometry']['a']['direction'] = [0, 0, 0]
        with self.assertRaises(ValueError): run_module('assembly', request)
        request = example(); request['mates'][0]['geometry']['a']['point_mm'] = [0, True, 0]
        with self.assertRaises(ValueError): run_module('assembly', request)

    def test_degenerate_angle_is_rejected(self):
        components = [{'id': 'base', 'fixed': True}, {'id': 'arm'}]
        flat = mate('flat', 'base', 'arm', 'angle', plane((0, 0, 0), (1, 0, 0)), plane((0, 0, 0), (1, 0, 0)),
                    angle={'value': 0, 'unit': 'deg', 'source': SOURCE})
        with self.assertRaises(ValueError): run_module('assembly', {'components': components, 'mates': [flat]})

    def test_mate_between_fixed_components_is_flagged(self):
        request = example()
        request['components'].append({'id': 'base', 'fixed': True})
        request['mates'].append(mate('bolted', 'frame', 'base', 'coincident', plane((0, 0, -50), (0, 0, 1)), plane((0, 0, -50), (0, 0, -1))))
        report = run_module('assembly', request)
        self.assertIn('mate_between_fixed_components:bolted', report['issues'])
        self.assertEqual(report['constraint_rank']['mobility'], 1)

    def test_size_limit(self):
        components = [{'id': 'ground', 'fixed': True}]+[{'id': 'p%d' % i} for i in range(MAX_MOVING_COMPONENTS+1)]
        with self.assertRaises(ValueError):
            analyse_constraints(components, [mate('m', 'ground', 'p0', 'coincident', point((0, 0, 0)), point((0, 0, 0)))])

    def test_scalar_table_accepts_perpendicular(self):
        result = inspect_assembly([{'id': 'a', 'fixed': True}, {'id': 'b'}], [{'a': 'a', 'b': 'b', 'type': 'perpendicular'}])
        kinds = [row['kind'] for row in result['issues']]
        self.assertNotIn('unsupported_mate', kinds)
        self.assertNotIn('unanchored', kinds)
        self.assertEqual(result['estimated_dof']['b'], 5)


if __name__ == '__main__':
    unittest.main()
