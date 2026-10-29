"""Workflow approval, source integrity and native dispatch boundaries, no real COM."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from project_delivery import (prepare_workflow,approve_workflow,workflow_status,execute_workflow,read_json)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'roller.SLDPRT';self.source.write_bytes(b'fake model, not CAD evidence')
        original=read_json(ROOT/'examples/unified-project.json')
        self.request={k:deepcopy(original[k]) for k in ('schema_version','roller','roller_intentions')}
        self.request['roller']['source_document']=str(self.source)
        for row in self.request['roller']['mappings']['parameters']:row['document']=str(self.source)
        self.request['roller_intentions']['dependency_graph']={'shaft_length':['barrel_length']}
        self.request['roller_intentions']['parameters']['shaft_length']={'role':'adjustable','unit':'mm','review_status':'confirmed','source':'explicit test fixture intent','allowed_range':[100,2000]}
        self.workspace=self.root/'workflow'

    def prepare(self):return prepare_workflow(self.request,self.workspace)
    def approve(self):
        status=self.prepare()
        return approve_workflow(self.workspace,reviewer='Fixture reviewer',review_sha256=status['review_sha256'])

    def test_prepare_links_impact_to_same_request_and_keeps_native_disabled(self):
        report=self.prepare();self.assertEqual(report['phase'],'review_required')
        self.assertFalse(report['native_write_allowed']);self.assertTrue(report['review_sha256'])
        before=self.source.read_bytes();self.approved=approve_workflow(self.workspace,reviewer='Engineer',review_sha256=report['review_sha256'])
        self.assertEqual(self.approved['phase'],'review_recorded');self.assertEqual(self.source.read_bytes(),before)

    def test_missing_real_sources_blocks_approval(self):
        self.source.unlink();status=self.prepare()
        self.assertEqual(status['phase'],'inputs_required')
        with self.assertRaises(ValueError):approve_workflow(self.workspace,reviewer='Engineer',review_sha256=status['review_sha256'])

    def test_original_change_invalidates_review(self):
        self.approve();self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'original model changed'):workflow_status(self.workspace)

    def test_plan_change_invalidates_review(self):
        self.prepare();(self.workspace/'planning/request.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'planning artifacts changed'):workflow_status(self.workspace)

    def test_implementation_change_invalidates_review(self):
        self.prepare()
        with patch('project_delivery.code_hashes',return_value={'different.py':'changed'}):
            with self.assertRaisesRegex(ValueError,'implementation changed'):workflow_status(self.workspace)

    def test_wrong_digest_empty_reviewer_and_repeat_approval_rejected(self):
        status=self.prepare()
        for reviewer,digest in [('Engineer','wrong'),('',status['review_sha256'])]:
            with self.assertRaises(ValueError):approve_workflow(self.workspace,reviewer=reviewer,review_sha256=digest)
        approve_workflow(self.workspace,reviewer='Engineer',review_sha256=status['review_sha256'])
        with self.assertRaises(FileExistsError):approve_workflow(self.workspace,reviewer='Engineer',review_sha256=status['review_sha256'])

    def test_linux_execute_refuses_before_claim_or_native_import(self):
        status=self.approve()
        with patch('project_delivery.sys.platform','linux'),patch('roller_variant.native.run_native') as run:
            with self.assertRaises(RuntimeError):execute_workflow(self.workspace,sw_exe='missing',approval_sha256=status['approval_sha256'])
        run.assert_not_called();self.assertFalse((self.workspace/'execution-claim.json').exists())

    def test_explicit_native_reuses_existing_driver_once_and_preserves_failure(self):
        status=self.approve();exe=self.root/'SLDWORKS.exe';exe.touch()
        with patch('project_delivery.sys.platform','win32'),patch('roller_variant.native.run_native',side_effect=RuntimeError('fake COM failure')) as run:
            result=execute_workflow(self.workspace,sw_exe=exe,approval_sha256=status['approval_sha256'])
            self.assertEqual(result['status'],'failed');self.assertFalse(result['manufacturing_approved'])
            with self.assertRaises(FileExistsError):execute_workflow(self.workspace,sw_exe=exe,approval_sha256=status['approval_sha256'])
        self.assertEqual(run.call_count,1);self.assertTrue((self.workspace/'execution.json').exists())

    def test_wrong_approval_digest_cannot_reach_native_driver(self):
        self.approve()
        with patch('roller_variant.native.run_native') as run:
            with self.assertRaisesRegex(ValueError,'approval digest'):execute_workflow(self.workspace,sw_exe='unused',approval_sha256='wrong')
        run.assert_not_called()


if __name__=='__main__':unittest.main()
