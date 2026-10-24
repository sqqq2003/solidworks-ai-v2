"""Native gate contracts; mocked math/COM only, no application launched."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, MagicMock
import solidworks_generator as sw


class NativeBendBatchTests(unittest.TestCase):
    def oracle(self, actual, expected=(.01,.02,0)):
        native = NS(ArrayData=actual)
        point = NS(MultiplyTransform=lambda transform:native)
        utility = NS(CreatePoint=lambda coords:point)
        app = NS(GetMathUtility=utility)
        lease = NS(native_launch=NS(app=app))
        transform = NS(ArrayData=(1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0))
        with patch.object(sw,'require_model_write',return_value=lease), \
             patch.object(sw,'_as_interface',side_effect=lambda m,o,n:o):
            return sw._verified_bend_sketch_point(None,transform,expected)

    def test_native_math_agrees_before_line_write(self):
        self.assertEqual(self.oracle((.01,.02,0)),(.01,.02))

    def test_native_mismatch_and_off_plane_refused(self):
        for actual in ((.02,.01,0),(.01,.02,.001),(float('nan'),0,0)):
            with self.subTest(actual=actual),self.assertRaises(sw.SolidWorksGenerationError):
                self.oracle(actual)

    def test_native_math_requires_owned_binding(self):
        with patch.object(sw,'require_model_write',return_value=NS(native_launch=None)):
            with self.assertRaises(sw.SessionOwnershipError):
                sw._verified_bend_sketch_point(None,None,(0,0,0))

    def test_insert_null_and_selection_failure_have_distinct_stages(self):
        for selected,stage in ((False,'select_sketch'),(True,'insert')):
            detail={}
            feature_manager=NS(InsertSheetMetal3dBend=lambda *a:None)
            with patch.object(sw,'_select_bend_sketch_for_feature',return_value=selected), \
                 patch.object(sw,'_call_with_sw_watchdog',side_effect=lambda t,fn:fn()):
                result=sw._try_insert_sheet_metal_bend(MagicMock(),feature_manager,
                    NS(SelectByID2=lambda *a:True),None,None,None,(0,0,0),1,.001,False,1,False,None,
                    diagnostic=detail)
            self.assertFalse(result)
            self.assertEqual(detail['stage'],stage)
            self.assertEqual(detail['status'],'failed')

    def test_single_attempt_port_does_not_call_relief_wrapper(self):
        from sheet_metal_windows import WindowsSheetMetalPort
        from dataclasses import dataclass
        @dataclass
        class Result:
            path: Path
            bend_count: int=4
        plan={'profile_index':0,'bend_indices':[0,1,2,3], 'relief_bend_indices':[],
              'parameters':{'thickness_mm':2.5,'radius_mm':1,'angle_degrees':90,'flip_direction':False},
              'bend_allowance':{'spec':{'mode':'k_factor','k_factor':.4}}}
        port=WindowsSheetMetalPort(allow_relief_retries=False)
        with patch.object(port,'guard'),patch.object(sw,'generate_sheet_metal',return_value=Result(Path('new.SLDPRT'))) as generate, \
             patch.object(sw,'generate_sheet_metal_with_relief_retries') as retry:
            self.assertEqual(port.generate(None,plan,Path('new.SLDPRT'))['bend_count'],4)
        generate.assert_called_once()
        retry.assert_not_called()

    def test_evidence_checker_refuses_simulation_and_partial_results(self):
        from sheet_metal_acceptance import audit_report
        report=audit_report({'plan':{'bend_indices':[0,1,2,3]},
            'execution':{'status':'simulated_pass','simulated_only':True,
            'generation':{'auto_bent':True,'bend_count':2}}})
        self.assertEqual(report['status'],'review_required')
        self.assertIn('incomplete_native_bends',report['issues'])
        self.assertIn('owned_session_evidence_missing',report['issues'])
        self.assertFalse(report['cad_executed'])
