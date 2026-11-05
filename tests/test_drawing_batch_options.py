import unittest
from ql5050px.auto_layout import first_angle_layout
from src.ql5050px.drawing_trial import validate_trial_case,verify_part_size,trial_task


class DrawingBatchOptionsTests(unittest.TestCase):
    def test_centered_group_keeps_first_angle_alignment_and_requested_sizes(self):
        sizes={'front':[22,24],'top':[22,70],'right':[70,24]}
        old=first_angle_layout(594,420,sizes)
        new=first_angle_layout(594,420,sizes,centered=True)
        self.assertGreater(new['front'][0],old['front'][0]+100)
        self.assertGreater(new['front'][1],old['front'][1]+100)
        self.assertEqual(new['front'][0],new['top'][0])
        self.assertEqual(new['front'][1],new['right'][1])
        self.assertLess(new['right'][0],new['front'][0]);self.assertLess(new['top'][1],new['front'][1])
    def test_valid_sheet_and_scale_matrix_preserves_explicit_choices(self):
        for sheet in ('A2','A3'):
            for denominator in (2,5,10,20):
                case={'sheet':sheet,'denominator':denominator}
                with self.subTest(case=case):
                    self.assertEqual(validate_trial_case(case),case)
                    task=trial_task(case,'frame','Default','bom',model_kind=1)
                    self.assertTrue(task['center_views']);self.assertEqual(task['scale'],[1,denominator])
    def test_invalid_cases_rejected_before_native_entry(self):
        for case in (None,{},dict(sheet='A4',denominator=10),dict(sheet='A2',denominator=True),dict(sheet='A2',denominator=0),dict(sheet='A2',denominator='5')):
            with self.subTest(case=case),self.assertRaises(ValueError):validate_trial_case(case)
    def test_geometry_expectation_binds_model_bytes_and_actual_extents(self):
        expected=dict(source_sha256='sha',size_mm=[40,60,514],tolerance_mm=.01)
        result=verify_part_size([0,-60,-514,40,0,0],expected,'sha')
        self.assertTrue(result['expected_size_verified']);self.assertFalse(result['manufacturing_approved'])
        with self.assertRaises(ValueError):verify_part_size([0,-60,-514,40,0,0],expected,'changed-sha')
        with self.assertRaises(RuntimeError):verify_part_size([0,-60,-504,40,0,0],expected,'sha')
    def test_unknown_geometry_never_becomes_confirmed_expected_size(self):
        result=verify_part_size([0,0,0,40,60,514],None,'sha')
        self.assertNotIn('expected_size_verified',result)
    def test_bad_geometry_or_unbounded_tolerance_rejected(self):
        expected=dict(source_sha256='sha',size_mm=[40,60,514],tolerance_mm=100)
        with self.assertRaises(ValueError):verify_part_size([0,0,0,40,60,514],expected,'sha')
        for bounds in ([0,0,0,float('nan'),60,514],[0,0,0,-40,60,514],[0,0]):
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):verify_part_size(bounds,None,'sha')
