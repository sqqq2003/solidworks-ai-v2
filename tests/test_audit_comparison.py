"""Compare candidate-specific evidence without closing engineering defects."""
from copy import deepcopy
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from release_evidence import compare_audits,save_audit,audit_submission

class ComparisonTests(unittest.TestCase):
    def report(self,status='failed',sha='a'*40):
        return {'scope':'declared_coverage_and_file_integrity_only','status':status,'repair_tasks':[],
            'results':[{'sha':sha,'lane':'native','id':'rebuild','status':status,'issues':[] if status=='passed' else ['missing_result']}]}
    def test_repaired_evidence_keeps_independent_engineering_review(self):
        result=compare_audits(self.report(),self.report('passed'))
        self.assertEqual(result['changes'][0]['kind'],'evidence_improved_requires_engineering_review')
        self.assertFalse(result['engineering_defects_auto_closed']);self.assertFalse(result['manufacturing_approved'])
    def test_regression_and_unreported_checks_are_visible(self):
        result=compare_audits(self.report('passed'),self.report())
        self.assertEqual(result['changes'][0]['kind'],'regression')
        newer=self.report();newer['results']=[]
        self.assertEqual(compare_audits(self.report(),newer)['changes'][0]['kind'],'no_longer_reported')
    def test_other_revision_cannot_resolve_old_candidate_issue(self):
        result=compare_audits(self.report(),self.report('passed','b'*40))
        self.assertEqual(set(result['counts']),{'new_check_or_candidate','no_longer_reported'})
        self.assertTrue(all(not r['resolved_evidence_issues'] for r in result['changes']))
    def test_identical_reports_have_no_changes(self):
        self.assertEqual(compare_audits(self.report(),self.report())['changes'],[])
    def test_wrong_scope_and_duplicate_identity_rejected(self):
        for wrong in ({'scope':'mechanical_acceptance'},self.report()):
            if wrong.get('results'):wrong['results']*=2
            with self.assertRaises(ValueError):compare_audits(wrong,self.report())
    def test_report_receipt_hashes_and_non_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'report';result=save_audit(self.report('passed'),dest,previous=self.report())
            self.assertTrue((dest/'comparison.json').exists());receipt=json.loads((dest/'receipt.json').read_text())
            for name,digest in receipt['files'].items():self.assertEqual(hashlib.sha256((dest/name).read_bytes()).hexdigest(),digest)
            with self.assertRaises(FileExistsError):save_audit(self.report(),dest)
    def test_task_identity_includes_source_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            ids=[]
            for sha in ('a'*40,'b'*40):
                matrix={'schema_version':1,'lanes':[{'id':'lane','sha':sha,'checks':[{'id':'check','scope':'offline'}]}]}
                result=audit_submission(matrix,{'schema_version':1,'results':[]},temp);ids.append(result['repair_tasks'][0]['id'])
            self.assertNotEqual(*ids)

if __name__=='__main__':unittest.main()
