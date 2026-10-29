"""Read-only stale-workspace diagnostics and revision lineage, without CAD."""
from copy import deepcopy
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from project_delivery import (read_json,prepare_workflow,approve_workflow,inspect_workspace,
                              revise_workflow,file_hash,request_changes)

class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.model=self.root/'model.SLDPRT';self.model.write_bytes(b'fake model')
        sample=read_json(ROOT/'examples/unified-project.json');self.request={k:deepcopy(sample[k]) for k in ('schema_version','roller','roller_intentions')}
        self.request['roller']['source_document']=str(self.model)
        for row in self.request['roller']['mappings']['parameters']:row['document']=str(self.model)
        intent=self.request['roller_intentions'];intent['dependency_graph']={'shaft_length':['barrel_length']}
        intent['parameters']['shaft_length']={'role':'adjustable','unit':'mm','review_status':'confirmed','source':'test fixture','allowed_range':[100,2000]}
        self.workspace=self.root/'old';self.initial=prepare_workflow(self.request,self.workspace)
    def test_stale_source_is_explained_without_rewriting_or_granting_writes(self):
        before=file_hash(self.workspace/'workflow.json');self.model.write_bytes(b'changed')
        result=inspect_workspace(self.workspace)
        self.assertIn('source_model_changed',[r['code'] for r in result['issues']])
        self.assertFalse(result['native_write_allowed']);self.assertEqual(file_hash(self.workspace/'workflow.json'),before)
    def test_changed_code_and_missing_plan_are_reported_together(self):
        (self.workspace/'planning/request.json').unlink()
        with patch('project_delivery.code_hashes',return_value={}):result=inspect_workspace(self.workspace)
        self.assertTrue({'implementation_changed','planning_file_missing'}<={r['code'] for r in result['issues']})
    def test_corrupt_manifest_remains_readable_as_diagnostic_failure(self):
        (self.workspace/'workflow.json').write_text('{}')
        self.assertEqual(inspect_workspace(self.workspace)['phase'],'invalid_workspace')
    def test_revision_replans_without_copying_approval_or_mutating_parent(self):
        approve_workflow(self.workspace,reviewer='fixture reviewer',review_sha256=self.initial['review_sha256'])
        before={p.name:file_hash(p) for p in self.workspace.iterdir() if p.is_file()}
        changed=deepcopy(self.request);changed['roller']['target_overall_mm']=900
        result=revise_workflow(self.workspace,changed,self.root/'new',reason='new required total length')
        self.assertFalse((self.root/'new/approval.json').exists());self.assertFalse(result['revision']['approval_carried_over'])
        self.assertEqual(before,{p.name:file_hash(p) for p in self.workspace.iterdir() if p.is_file()})
        self.assertEqual(result['revision']['parent_workspace_id'],self.initial['workspace_id'])
        self.assertTrue(any(r['path']=='/roller/target_overall_mm' for r in result['revision']['changes']))
    def test_identical_request_can_be_replanned_after_implementation_change(self):
        with patch('project_delivery.code_hashes',return_value={}):
            result=revise_workflow(self.workspace,self.request,self.root/'recode',reason='implementation update')
        self.assertFalse(result['revision']['approval_carried_over'])
    def test_unresolved_execution_claim_cannot_be_bypassed_by_revision(self):
        (self.workspace/'execution-claim.json').write_text('{}')
        changed=deepcopy(self.request);changed['roller']['target_overall_mm']=900
        self.assertFalse(inspect_workspace(self.workspace)['revision_allowed'])
        with self.assertRaisesRegex(ValueError,'execution claim'):revise_workflow(self.workspace,changed,self.root/'new',reason='retry')
        self.assertFalse((self.root/'new').exists())
    def test_nested_or_identical_revision_is_refused(self):
        for destination in (self.workspace/'inside',self.root/'same'):
            with self.assertRaises(ValueError):revise_workflow(self.workspace,self.request,destination,reason='fixture')
        self.assertFalse((self.root/'same').exists())
    def test_revision_lineage_is_bound_to_the_new_workspace(self):
        from project_delivery import workflow_status
        changed=deepcopy(self.request);changed['roller']['target_overall_mm']=900
        dest=self.root/'new';revise_workflow(self.workspace,changed,dest,reason='confirmed target change')
        (dest/'revision.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'revision lineage'):workflow_status(dest)
        self.assertIn('revision_lineage_changed',[r['code'] for r in inspect_workspace(dest)['issues']])
    def test_typed_values_are_not_silently_equated(self):
        self.assertTrue(request_changes({'enabled':True},{'enabled':1}))

if __name__=='__main__':unittest.main()
