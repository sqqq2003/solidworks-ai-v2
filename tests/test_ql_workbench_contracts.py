"""Integration regression source; NOT RUN in the development-only batch."""
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'src')]
from project_workbench import build_command, run_batch
from ql5050px.workflow import run_workflow


class QLWorkbenchContracts(unittest.TestCase):
    def test_target_is_not_physical_mapping(self):
        result = run_workflow('plan',{'machine':'QL-5050PX'})
        self.assertEqual(result['status'],'pending_mapping')
        self.assertFalse(result['cad_executed'])
        self.assertEqual(result['plan']['values_mm']['target_length'],1800)
        self.assertEqual(result['plan']['physical_mapping_register']['target_length']['status'],'pending_mapping')

    def test_other_machine_rejected(self):
        with self.assertRaises(ValueError):
            run_workflow('plan',{'machine':'GT-ZX'})

    def test_missing_assembly_not_an_acceptance(self):
        result = run_workflow('assembly',{})
        self.assertTrue(any(r['kind']=='missing_assembly' for r in result['assembly']['issues']))
        self.assertEqual(result['mechanical_acceptance'],'unverified')

    def test_ql_command_and_review_required_batch(self):
        command = build_command({'kind':'ql5050px','action':'plan','request':{}})
        self.assertIn('--request-json',command)
        report = run_batch([{'kind':'ql5050px','action':'plan','request':{}}],
            execute=lambda job:{'status':'pending_mapping'})
        self.assertEqual(report['status'],'review_required')

    def test_bom_and_drawing_export_without_native_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)/'new'
            config = {'components':[{'id':'frame','module':'frame','component_kind':'fixed',
                       'part_number':'SIM-FRAME','quantity':1,'material':'simulation'}]}
            result = run_workflow('drawing',config,output_dir=folder)
            self.assertTrue((folder/'bom.csv').is_file())
            self.assertTrue((folder/'drawing.json').is_file())
            self.assertEqual(result['native_exports']['SLDDRW']['status'],'pending_windows')
            with self.assertRaises(FileExistsError):
                run_workflow('drawing',config,output_dir=folder)
