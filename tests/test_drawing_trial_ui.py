import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from drawing_trial_app import inspect_trial_result,run_trial_worker


class DrawingUiTests(unittest.TestCase):
    def test_process_launch_failure_returns_terminal_error(self):
        with tempfile.TemporaryDirectory() as folder,patch('drawing_trial_app.subprocess.Popen',side_effect=OSError('launch failed')):
            code,error=run_trial_worker(['never-executed'],Path(folder)/'worker.log')
            self.assertIsNone(code);self.assertIn('launch failed',error)

    def test_log_creation_failure_does_not_launch_worker(self):
        with tempfile.TemporaryDirectory() as folder,patch('drawing_trial_app.subprocess.Popen') as launch:
            code,error=run_trial_worker(['never-executed'],Path(folder)/'absent'/'log')
            launch.assert_not_called();self.assertIsNotNone(error)

    def test_corrupt_report_does_not_crash_poll_or_report_success(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'result.json').write_text('{broken')
            result=inspect_trial_result(0,folder)
            self.assertFalse(result['drawing_generated']);self.assertTrue(result['error'])

    def test_empty_report_is_not_mislabeled_as_sheet_too_small(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'result.json').write_text(json.dumps({'cells':[]}))
            result=inspect_trial_result(0,folder)
            self.assertFalse(result['drawing_generated']);self.assertNotIn('比例装不下',result['message'])

    def test_success_and_blocked_statuses_stay_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'result.json'
            for status in ('pass_pending_visual','expected_layout_block','failed'):
                path.write_text(json.dumps({'cells':[{'status':status}]}))
                result=inspect_trial_result(0,folder)
                self.assertEqual(result['drawing_generated'],status=='pass_pending_visual')
                self.assertEqual('比例装不下' in result['message'],status=='expected_layout_block')

    def test_generated_trial_shows_missing_reference_count(self):
        with tempfile.TemporaryDirectory() as folder:
            report={'cells':[{'status':'pass_pending_visual'}],
                    'components':[{'exists':False},{'exists':True},{'exists':False}]}
            (Path(folder)/'result.json').write_text(json.dumps(report))
            result=inspect_trial_result(0,folder)
            self.assertTrue(result['drawing_generated'])
            self.assertEqual(result['missing_component_references'],2)
            self.assertIn('2 个缺失组件引用',result['message'])
            self.assertIn('未通过生产验收',result['message'])
