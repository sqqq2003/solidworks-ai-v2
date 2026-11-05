"""User-supplied frame rules must stay planning-only until independently bound."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from parametric_workspace import preview_parameters,save_parameter_workspace


def fixture():
    return {'pitch_mm':88.9,'mother_width_mm':600,'mother_length_mm':1000,
            'mother_height_mm':455,'mother_margin_start_mm':75.785,
            'mother_margin_end_mm':124.115,'mother_side_plate_height_mm':100,
            'mother_side_plate_thickness_mm':None,'mother_shaft_stickout_mm':None,
            'mother_drive_side':None,'drive_side':None,
            'geometry_drive':{'mother_inner_span_mm':694.606,'length_mode':'pattern_only'}}


class FramePreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'frame.json'

    def preview(self,config=None,**dimensions):
        self.path.write_text(json.dumps(config if config is not None else fixture()),encoding='utf8')
        return preview_parameters(dimensions.get('length',1500),dimensions.get('width',800),dimensions.get('height',500),spec_path=self.path)

    def test_frame_semantics_pitch_leg_only_and_unknown_outer_width(self):
        result=self.preview();plan=result['plan'];values=plan['values_mm']
        self.assertNotIn('target_envelope_mm',result)
        self.assertEqual(plan['width_definition'],'side_plate_inner_clear_span')
        self.assertEqual(values['inner_clear_width'],800)
        self.assertEqual(values['side_plate_height'],100)
        self.assertEqual(values['leg_length'],400)
        self.assertEqual(values['leg_delta'],45)
        self.assertIsNone(values['outer_width'])
        centers=plan['hole_centers_mm']
        self.assertTrue(all(abs(b-a-88.9)<1e-6 for a,b in zip(centers,centers[1:])))
        self.assertTrue(any('694.606' in warning for warning in plan['warnings']))
        self.assertFalse(result['native_write_allowed'])
        self.assertFalse(result['manufacturing_approved'])
        target=Path(self.temp.name)/'export';save_parameter_workspace(result,target)
        self.assertTrue(all(r['status']=='pending_mapping' for r in json.loads((target/'model-mapping.json').read_text(encoding='utf8'))['parameters']))

    def test_height_change_without_measured_side_plate_height_refuses(self):
        config=fixture();config['mother_side_plate_height_mm']=None
        with self.assertRaisesRegex(ValueError,'侧板高度'):self.preview(config)

    def test_drive_swap_cannot_be_treated_as_implemented(self):
        config=fixture();config.update(mother_drive_side='left',drive_side='right')
        result=self.preview(config)
        self.assertEqual(result['plan']['drive_side']['action'],'swap')
        self.assertTrue(any('禁止执行' in w and '挡板' in w for w in result['plan']['warnings']))
        self.assertFalse(result['cad_executed'])
        config['mother_drive_side']=None
        with self.assertRaises(ValueError):self.preview(config)

    def test_yaml_import_and_unsafe_yaml_tags(self):
        import yaml
        path=self.path.with_suffix('.yaml');path.write_text(yaml.safe_dump(fixture()),encoding='utf8')
        result=preview_parameters(1500,800,500,spec_path=path)
        self.assertEqual(result['plan']['machine_id'],'roller_frame')
        path.write_text('!!python/object/apply:builtins.print [should_not_execute]',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'YAML'):preview_parameters(1500,800,500,spec_path=path)

    def test_resource_bounds_and_nonstandard_pitch_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'10000'):self.preview(length=1e6)
        config=fixture();config['pitch_mm']=90
        with self.assertRaisesRegex(ValueError,'88.9'):self.preview(config)
        config=fixture();config['mother_margin_start_mm']=1e308
        with self.assertRaises(ValueError):self.preview(config)
