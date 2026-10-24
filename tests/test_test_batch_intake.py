"""Offline evidence intake contracts; native validator mocked only for binding tests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from test_batch_intake import audit_batch


class BatchIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'fixture.dxf').write_bytes(b'synthetic fixture')
        self.case = dict(id='S2', executor='WB', source='fixture.dxf', report='report.json',
                         source_sha256=hashlib.sha256(b'synthetic fixture').hexdigest(),
                         code_sha256='a'*64, parameters={'k_factor':.4}, profile_index=0)
        self.report = dict(plan={k:self.case[k] for k in ('source_sha256','code_sha256','parameters','profile_index')})
        self.save()

    def save(self):
        data = json.dumps(self.report).encode()
        (self.root/'report.json').write_bytes(data)
        self.case['report_sha256'] = hashlib.sha256(data).hexdigest()

    def run_batch(self, cases=None):
        return audit_batch(dict(schema_version=1,cases=cases or [self.case]),self.root)

    @patch('test_batch_intake.audit_report',return_value={'issues':[]})
    def test_bound_record_consistent_without_claiming_live(self, audit):
        result=self.run_batch()
        self.assertEqual(result['counts'],dict(total=1,consistent=1,review_required=0))
        self.assertFalse(result['cad_executed'])
        self.assertEqual(result['mechanical_acceptance'],'unverified')

    @patch('test_batch_intake.audit_report',return_value={'issues':[]})
    def test_report_tamper_refused(self, audit):
        with (self.root/'report.json').open('ab') as stream:stream.write(b' ')
        self.assertIn('report_bytes_changed',self.run_batch()['cases'][0]['issues'])

    @patch('test_batch_intake.audit_report',return_value={'issues':[]})
    def test_wrong_fixture_and_code_and_parameters_refused(self, audit):
        (self.root/'fixture.dxf').write_bytes(b'other')
        self.report['plan'].update(code_sha256='b'*64,parameters={'k_factor':.5},profile_index=1)
        self.save()
        issues=self.run_batch()['cases'][0]['issues']
        for issue in ('fixture_bytes_changed','code_sha256_mismatch','expected_parameters_mismatch','profile_index_mismatch'):
            self.assertIn(issue,issues)

    def test_malformed_case_does_not_hide_following_failure(self):
        result=self.run_batch([None,self.case])
        self.assertEqual(result['counts']['review_required'],2)
        self.assertIn('native_result_missing_or_simulated',result['cases'][1]['issues'])

    @patch('test_batch_intake.audit_report',return_value={'issues':[]})
    def test_duplicates_are_not_double_counted_as_passes(self, audit):
        self.assertEqual(self.run_batch([self.case,self.case])['counts']['consistent'],1)

    def test_missing_report_and_path_escape(self):
        for path in ('missing.json','../outside.json'):
            self.case['report']=path
            self.assertEqual(self.run_batch()['counts']['review_required'],1)

    def test_real_validator_rejects_simulation(self):
        self.report['execution']={'status':'simulated_pass','simulated_only':True}
        self.save()
        self.assertIn('native_result_missing_or_simulated',self.run_batch()['cases'][0]['issues'])

    def test_empty_manifest_rejected(self):
        with self.assertRaises(ValueError):audit_batch({'schema_version':1,'cases':[]},self.root)

    def test_full_record_and_artifact_hashes_then_dirty_exit(self):
        # Synthetic records and arbitrary bytes only: exercises consistency, not CAD.
        from sheet_metal_pipeline import digest
        plan=self.report['plan']
        plan.update(bend_indices=[0])
        plan['parameters'].update(thickness_mm=2.5,radius_mm=1)
        plan['plan_id']=digest(plan)
        products={}
        for name in ('part.SLDPRT','flat.DXF'):
            (self.root/name).write_bytes(b'synthetic test bytes')
            products[name]=hashlib.sha256(b'synthetic test bytes').hexdigest()
        self.report.update(session=dict(ownership='spawned_pid_and_live_handle',attached_existing=False,
                                        cleanup_exit_code=0),
            execution=dict(status='native_features_verified',simulated_only=False,plan_id=plan['plan_id'],
                generation=dict(auto_bent=True,bend_count=1),output_dir=str(self.root),artifact_sha256=products,
                reopen=dict(reopened=True,rebuilt=True,editable=True,bend_feature_count=1,
                    feature_types=['SheetMetal','FlatPattern','SMBaseFlange'],thickness_mm=2.5,radius_mm=1,k_factor=.4)))
        self.save()
        self.assertEqual(self.run_batch()['counts']['consistent'],1)
        self.report['session']['cleanup_exit_code']=139
        self.save()
        self.assertIn('clean_process_exit_unverified',self.run_batch()['cases'][0]['issues'])
        self.report['session']['cleanup_exit_code']=0
        self.save()
        (self.root/'flat.DXF').write_bytes(b'changed')
        self.assertIn('artifact_empty_or_changed: flat.DXF',self.run_batch()['cases'][0]['issues'])
