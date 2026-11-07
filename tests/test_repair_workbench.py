import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from ql5050px.repair_workbench import prepare_trial,validate_trial


class RepairWorkbenchTests(unittest.TestCase):
    def fixture(self,folder):
        root=Path(folder);source=root/'part.step';source.write_bytes(b'synthetic CAD baseline')
        spec=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  axis_point_mm=[10,0,0],axis_direction=[0,0,1],
                  cylinder_radius_mm=25,slot_center_mm=[0,0],existing_radius_mm=35,
                  slab_z_mm=[0,2],trial_clearance_mm=.2,radius_grid_mm=1,
                  max_trial_increase_mm=2,trial_authorized=True)
        path=root/'spec.json';path.write_text(json.dumps(spec),encoding='utf-8')
        return source,path,root/'output'

    def test_prepare_validate_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            source,spec,out=self.fixture(folder);before=source.read_bytes()
            result=prepare_trial(source,spec,out)
            self.assertEqual(result['target_radius_mm'],36)
            self.assertEqual(validate_trial(source,result['plan'])['status'],'trial_plan_valid')
            self.assertEqual(source.read_bytes(),before)
            self.assertFalse(result['cad_executed'])

    def test_changed_source_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            source,spec,out=self.fixture(folder);source.write_bytes(b'changed')
            with self.assertRaises(ValueError):prepare_trial(source,spec,out)
            self.assertFalse(out.exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            source,spec,out=self.fixture(folder);out.mkdir();old=out/'trial-plan.json';old.write_bytes(b'original')
            with self.assertRaises(FileExistsError):prepare_trial(source,spec,out)
            self.assertEqual(old.read_bytes(),b'original')

    def test_changed_plan_is_rejected_on_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            source,spec,out=self.fixture(folder);result=prepare_trial(source,spec,out)
            path=Path(result['plan']);data=json.loads(path.read_text());data['target_radius_mm']=100
            path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError):validate_trial(source,path)

    def test_review_required_plan_is_displayable_but_not_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            source,spec,out=self.fixture(folder);data=json.loads(spec.read_text());data['trial_authorized']=False
            spec.write_text(json.dumps(data),encoding='utf-8')
            result=prepare_trial(source,spec,out)
            self.assertEqual(result['status'],'review_required')
            with self.assertRaises(ValueError):validate_trial(source,result['plan'])
