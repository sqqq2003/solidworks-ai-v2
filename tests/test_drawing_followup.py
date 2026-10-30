"""Actual retest envelopes, fake COM lag, and explicit alternatives; no CAD."""
from copy import deepcopy
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from drawing_review import DrawingEvidence
from drawing_trial_app import inspect_trial_result
from ql5050px.auto_layout import explicit_fit_alternatives,LayoutDoesNotFit
from ql5050px.drawing_verification import lock_view_layout
import test_drawing_verification as drawing_fixtures


class FollowupTests(unittest.TestCase):
    def sizes(self):return {'front':[110.5,143.0],'top':[110.5,180.32],'right':[180.32,143.0]}

    def test_d4_alternatives_are_explicit_and_do_not_change_input_ratio(self):
        sizes=self.sizes();before=deepcopy(sizes);scale=[1,10]
        choices=explicit_fit_alternatives(sizes,scale,[420,297])
        self.assertEqual([(c['sheet'],c['scale']) for c in choices],
                         [('A2',[1,10]),('A2',[1,20]),('A3',[1,20])])
        self.assertEqual(sizes,before);self.assertEqual(scale,[1,10])
        self.assertTrue(all(c['explicit_user_choice_required'] and c['native_and_visual_review_required'] for c in choices))

    def test_refusal_has_atomic_json_ready_fields_without_lowering_scale(self):
        helper=drawing_fixtures.FrameFitLayoutTests();drawing,sheet=helper._sheet(1,10,420,297)
        task=helper._task([1,10],420,297)
        views={name:drawing_fixtures._AnchoredView(size,[0,0],.1) for name,size in self.sizes().items()}
        with self.assertRaises(LayoutDoesNotFit) as caught:lock_view_layout(drawing,task,views)
        error=caught.exception
        self.assertEqual(error.diagnostic['sheet_mm'],[420.,297.]);self.assertEqual(error.diagnostic['scale'],[1,10])
        self.assertEqual(set(error.diagnostic['outlines_mm']),{'front','top','right'})
        self.assertTrue(error.alternatives);sheet.SetScale.assert_called_once_with(1,10,True,True)
        self.assertEqual(task['scale'],[1,10])
        with tempfile.TemporaryDirectory() as folder:
            page=DrawingEvidence(Path(folder)/'page.json',{'id':'A3_1-10'},simulated_only=True)
            page.fail(error);data=json.loads(page.path.read_bytes())
            self.assertEqual(data['state'],'failed');self.assertFalse(data['complete'])
            self.assertEqual(data['layout_diagnostic'],error.diagnostic)
            self.assertEqual(data['explicit_fit_alternatives'],error.alternatives)

    def test_ui_partial_three_of_six_never_reports_whole_delivery_pass(self):
        choices=explicit_fit_alternatives(self.sizes(),[1,10],[420,297])
        cells=[{'status':'pass_pending_visual'} for _ in range(3)]+[
            {'status':'expected_layout_block','explicit_fit_alternatives':choices} for _ in range(3)]
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'result.json').write_text(json.dumps({'cells':cells}))
            report=inspect_trial_result(0,folder)
        self.assertEqual(report['generated_count'],3);self.assertEqual(report['blocked_count'],3)
        self.assertFalse(report['drawing_generated']);self.assertFalse(report['delivery_accepted'])
        self.assertIn('3/6',report['message']);self.assertIn('明确选择',report['message'])

    def test_ui_all_blocked_returns_choices_without_native_reexecution(self):
        choices=explicit_fit_alternatives(self.sizes(),[1,10],[420,297])
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'result.json').write_text(json.dumps({'cells':[{
                'status':'expected_layout_block','explicit_fit_alternatives':choices}]}))
            with patch('drawing_trial_app.subprocess.Popen') as launch:
                result=inspect_trial_result(0,folder)
            launch.assert_not_called();self.assertEqual(len(result['fit_alternatives']),3)
            self.assertFalse(result['visual_accepted'])


if __name__=='__main__':unittest.main()
