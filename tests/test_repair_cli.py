import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from ql5050px.repair_cli import main


class RepairCliTests(unittest.TestCase):
    def fixture(self,folder):
        source=Path(folder)/'source.step';source.write_bytes(b'test baseline')
        spec=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  axis_point_mm=[10,0,-10], axis_direction=[0,0,2], cylinder_radius_mm=25,
                  slot_center_mm=[0,0], existing_radius_mm=35, slab_z_mm=[-1,1],
                  trial_clearance_mm=.2, radius_grid_mm=1, max_trial_increase_mm=2,
                  trial_authorized=True)
        specpath=Path(folder)/'spec.json';specpath.write_text(json.dumps(spec),encoding='utf-8')
        return source,specpath,Path(folder)/'plan.json'

    def test_prepare_then_validate_without_cad(self):
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stdout(io.StringIO()):
            source,spec,plan=self.fixture(folder)
            self.assertEqual(main(['plan-slot','--source',str(source),'--spec',str(spec),'--output',str(plan)]),0)
            self.assertEqual(main(['validate-plan','--source',str(source),'--plan',str(plan)]),0)
            self.assertFalse(json.loads(plan.read_text())['cad_executed'])

    def test_changed_source_refuses_plan_creation(self):
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stderr(io.StringIO()):
            source,spec,plan=self.fixture(folder);source.write_bytes(b'changed')
            with self.assertRaises(SystemExit) as error:main(['plan-slot','--source',str(source),'--spec',str(spec),'--output',str(plan)])
            self.assertEqual(error.exception.code,2);self.assertFalse(plan.exists())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder,contextlib.redirect_stderr(io.StringIO()):
            source,spec,plan=self.fixture(folder);plan.write_bytes(b'original')
            with self.assertRaises(SystemExit):main(['plan-slot','--source',str(source),'--spec',str(spec),'--output',str(plan)])
            self.assertEqual(plan.read_bytes(),b'original')
