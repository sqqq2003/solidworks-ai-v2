"""Evidence intake rejects stale/mock/missing records and never executes archives."""
import hashlib,json
from pathlib import Path
import sys,tempfile,unittest,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from release_evidence import audit_submission,inspect_diagnostics


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.artifact=self.root/'check.json';self.artifact.write_text('{"fixture":true}')
        self.matrix={'schema_version':1,'lanes':[{'id':'candidate','sha':'a'*40,'checks':[{'id':'reopen','scope':'native'}]}]}
        self.row={'lane':'candidate','id':'reopen','sha':'a'*40,'scope':'native','status':'passed',
            'simulated_only':False,'session':{'ownership':'spawned_pid_and_live_handle','attached_existing':False},
            'environment':{'platform':'Windows','solidworks_version':'fake fixture'},'process_exit_code':0,
            'artifacts':[{'path':'check.json','sha256':hashlib.sha256(self.artifact.read_bytes()).hexdigest()}]}
    def audit(self):return audit_submission(self.matrix,{'schema_version':1,'results':[self.row]},self.root)
    def test_consistent_records_still_do_not_grant_manufacturing_approval(self):
        result=self.audit();self.assertEqual(result['status'],'passed');self.assertFalse(result['manufacturing_approved'])
        self.assertEqual(result['native_acceptance'],'requires_independent_review')
    def test_mock_or_missing_owned_session_cannot_be_native_pass(self):
        for key,value in [('simulated_only',True),('session',{})]:
            before=self.row[key];self.row[key]=value
            self.assertEqual(self.audit()['status'],'review_required');self.row[key]=before
    def test_stale_pin_and_missing_check_generate_explicit_followup(self):
        self.row['sha']='b'*40
        result=self.audit();self.assertIn('commit_mismatch',result['repair_tasks'][0]['reasons'])
        result=audit_submission(self.matrix,{'schema_version':1,'results':[]},self.root)
        self.assertIn('missing_result',result['repair_tasks'][0]['reasons'])
    def test_changed_artifact_or_crash_is_failure_and_p0_task(self):
        for edit in ('file','exit'):
            self.row['process_exit_code']=0
            self.artifact.write_text('{"fixture":true}' if edit=='exit' else 'changed')
            if edit=='exit':self.row['process_exit_code']=-1073741819
            result=self.audit();self.assertEqual(result['status'],'failed');self.assertEqual(result['repair_tasks'][0]['priority'],'P0')
    def test_declared_failure_stays_failure_without_native_proof(self):
        self.row.update(status='failed',simulated_only=True)
        self.assertEqual(self.audit()['status'],'failed')
    def test_diagnostic_journal_details_schema_and_deduplication(self):
        row={'event':'job_finished','details':{'status':'failed','errors':[{'message':'exclusive ownership missing'}]}}
        archive=self.root/'logs.zip'
        with zipfile.ZipFile(archive,'x') as z:
            z.writestr('logs/test.jsonl',json.dumps(row)+'\n'+json.dumps(row))
            z.writestr('never-run.py','raise RuntimeError("must not execute")')
        report=inspect_diagnostics(archive)
        self.assertEqual(len(report['findings']),1);self.assertEqual(report['findings'][0]['stage'],'dwg_conversion')
    def test_zip_traversal_and_size_limit_rejected_without_extracting(self):
        archive=self.root/'bad.zip'
        with zipfile.ZipFile(archive,'x') as z:z.writestr('../outside.jsonl','{}')
        with self.assertRaises(ValueError):inspect_diagnostics(archive)
        self.assertFalse((self.root.parent/'outside.jsonl').exists())
    def test_malformed_records_are_review_items(self):
        archive=self.root/'malformed.zip'
        with zipfile.ZipFile(archive,'x') as z:z.writestr('test.jsonl','not JSON\n')
        self.assertEqual(inspect_diagnostics(archive)['findings'][0]['kind'],'malformed_jsonl')


if __name__=='__main__':unittest.main()
