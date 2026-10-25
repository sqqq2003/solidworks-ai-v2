"""Focused offline contracts; fixture evidence is never a native run."""
from copy import deepcopy
import hashlib,json,tempfile,unittest
from pathlib import Path
from design_review import analyze_impact,record_approval,evaluate_acceptance,propose_repairs
from design_review.acceptance import PROFILES


def impact_fixture():
    plan={'status':'ready_for_native','changes':[{'parameter':'barrel_length','before_mm':945,'after_mm':745}],'affected_features':['BarrelExtrude'],'affected_mates':['right_support']}
    intent={'parameters':{'barrel_length':{'role':'adjustable','unit':'mm','allowed_range':[100,1500],'review_status':'confirmed','source':'synthetic fixture'},
        'shaft_diameter':{'role':'interface','unit':'mm','review_status':'confirmed','source':'synthetic fixture'}},
        'dependency_graph':{'shaft_length':['barrel_length'],'right_support':['shaft_length']}}
    return plan,intent

class IntentContracts(unittest.TestCase):
    def test_protection_and_transitive_impact_are_explicit(self):
        plan,intent=impact_fixture();r=analyze_impact(plan,intent)
        self.assertEqual(r['affected_parameters'],['barrel_length','right_support','shaft_length'])
        self.assertEqual(r['protected_readbacks'][0]['parameter'],'shaft_diameter')
        self.assertFalse(r['review_ready']);self.assertFalse(r['native_write_allowed'])
    def test_protected_change_is_failed_not_auto_corrected(self):
        plan,intent=impact_fixture();plan['changes']=[{'parameter':'shaft_diameter','before_mm':12,'after_mm':14}]
        r=analyze_impact(plan,intent);self.assertEqual(r['status'],'failed')
        self.assertEqual(r['conflicts'][0]['reason'],'protected_design_interface')
    def test_approval_bound_to_plan_and_intent(self):
        plan,intent=impact_fixture();intent['dependency_graph']={};r=analyze_impact(plan,intent)
        self.assertTrue(r['review_ready'])
        approval=record_approval(r,reviewer='fixture-reviewer',review_sha256=r['review_sha256'])
        self.assertFalse(approval['native_write_allowed'])
        r['changes'][0]['after']=800
        with self.assertRaisesRegex(ValueError,'stale'):record_approval(r,reviewer='fixture-reviewer',review_sha256=r['review_sha256'])
    def test_dependency_cycle_rejected(self):
        plan,intent=impact_fixture();intent['dependency_graph']={'a':['b'],'b':['a']}
        with self.assertRaisesRegex(ValueError,'cyclic'):analyze_impact(plan,intent)

class AcceptanceContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        content=b'fixture bytes, not a CAD file';(self.root/'fixture.SLDPRT').write_bytes(content)
        self.record={'profile':'roller','run_id':'fixture-run','source_revision':'a'*40,
            'artifacts':[{'name':'fixture.SLDPRT','role':'model','sha256':hashlib.sha256(content).hexdigest()}],
            'checks':[{'id':name,'status':'passed','execution':'native','evidence':{'source':'synthetic fixture only','run_id':'fixture-run','source_revision':'a'*40,
                'comparisons':[{'name':'fixture-dimension','expected':800,'actual':800,'tolerance':.01,'unit':'mm'}],
                'exit_code':0,'ownership':'spawned_pid_and_live_handle','attached_existing':False}} for name in PROFILES['roller']['checks']]}
    def run_assessment(self):return evaluate_acceptance(self.record,artifact_root=self.root)
    def test_four_states_follow_evidence_not_appearance(self):
        r=self.run_assessment();self.assertEqual(r['status'],'passed');self.assertFalse(r['cad_executed']);self.assertFalse(r['manufacturing_approved'])
        self.record['checks'].append({'id':'optional_preview','status':'failed'})
        self.assertEqual(self.run_assessment()['status'],'degraded')
        self.record['checks'][0]['status']='not_run'
        self.assertEqual(self.run_assessment()['status'],'review_required')
        self.record['checks'][0]['status']='failed'
        self.assertEqual(self.run_assessment()['status'],'failed')
    def test_offline_success_cannot_be_native_pass(self):
        for row in self.record['checks']:row['execution']='offline'
        self.assertEqual(self.run_assessment()['status'],'review_required')
    def test_exit_crash_cannot_pass(self):
        next(r for r in self.record['checks'] if r['id']=='process_exit')['evidence']['exit_code']=3221225477
        self.assertEqual(self.run_assessment()['status'],'failed')
    def test_wrong_revision_and_unknown_exit_require_review(self):
        self.record['checks'][1]['evidence']['source_revision']='b'*40
        self.assertEqual(self.run_assessment()['status'],'review_required')
        self.record['checks'][1]['evidence']['source_revision']='a'*40
        next(r for r in self.record['checks'] if r['id']=='process_exit')['evidence']['exit_code']=None
        self.assertEqual(self.run_assessment()['status'],'review_required')
    def test_numeric_mismatch_fails_even_when_runner_says_passed(self):
        row=next(r for r in self.record['checks'] if r['id']=='dimensions')
        row['evidence']['comparisons'][0]['actual']=745
        self.assertEqual(self.run_assessment()['status'],'failed')
    def test_missing_numeric_readback_requires_review(self):
        row=next(r for r in self.record['checks'] if r['id']=='dimensions')
        row['evidence'].pop('comparisons')
        self.assertEqual(self.run_assessment()['status'],'review_required')
    def test_artifact_tamper_fails(self):
        (self.root/'fixture.SLDPRT').write_bytes(b'changed')
        self.assertEqual(self.run_assessment()['status'],'failed')
    def test_owned_session_cannot_be_waived(self):
        row=next(r for r in self.record['checks'] if r['id']=='owned_session');row['evidence']['attached_existing']=True
        self.assertEqual(self.run_assessment()['status'],'review_required')
    def test_missing_checks_and_artifacts_require_review(self):
        self.record['checks']=[];self.record['artifacts']=[]
        self.assertEqual(self.run_assessment()['status'],'review_required')
    def test_repair_proposal_never_modifies_or_invents_dimensions(self):
        self.record['checks'][1]['status']='failed'
        result=propose_repairs(self.run_assessment())
        self.assertEqual(result['proposals'][0]['action'],'review_dimension_mapping')
        self.assertFalse(result['proposals'][0]['automatic_execution_allowed'])
        self.assertFalse(result['cad_executed'])
    def test_duplicate_check_refused(self):
        self.record['checks'].append(deepcopy(self.record['checks'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate'):self.run_assessment()

if __name__=='__main__':unittest.main()
