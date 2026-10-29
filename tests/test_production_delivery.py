"""Local fixture integrity and export contracts, no native CAD execution."""
import json,tempfile,unittest,zipfile
from copy import deepcopy
from pathlib import Path
from ql5050px.production import fingerprint,validate_review
from ql5050px.production_review import seal_production_review,verify_production_inputs,file_sha256
from ql5050px.production_acceptance import audit_production,export_production_acceptance

class DeliveryContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def plan(self):
        source=self.root/'source.SLDASM';source.write_bytes(b'fake source')
        template=self.root/'part.prtdot';template.write_bytes(b'fake template')
        p={'status':'ready_for_native','pending_mapping':[],
           'machine_plan':{'assembly_plan':{'status':'ready_for_native','tree':{'catalog':{'machine':{'source_path':str(source)},'part':{'template':str(template)}}}},
             'drive_plan':{'status':'ready_for_native'},'drawing_plan':{'status':'ready_for_native','tasks':[]}}}
        p['review_sha256']=fingerprint(p);return p
    def report(self):
        root=self.root/'run';root.mkdir();artifacts={};receipts={}
        for filename in ('machine.SLDASM','part.SLDPRT','machine.SLDDRW','bom.csv'):
            p=root/filename;p.write_bytes(b'offline fixture')
            artifacts[filename]=file_sha256(p)
            receipts[filename]={'path':str(p)}
        data={'review_sha256':'a'*64,'status':'outputs_created_review_required',
            'stages':[{'name':n,'status':'returned'} for n in ('assembly','drive','checks','drawings')],
            'artifact_sha256':artifacts,'documents':{'machine':receipts['machine.SLDASM'],'part':receipts['part.SLDPRT']},
            'drawings':{'results':[receipts['machine.SLDDRW']]},
            'input_verification':{'status':'declared_files_verified'},
            'mechanical_findings':{'simulated_only':False,'interference':[{'fixture':True}]}}
        (root/'checkpoint.json').write_text(json.dumps(data));return root,data
    def test_review_binds_inputs_and_code_then_rejects_changed_input(self):
        p=self.plan();sealed=seal_production_review(p)
        self.assertNotEqual(p['review_sha256'],sealed['review_sha256'])
        validate_review(sealed,sealed['review_sha256'])
        self.assertEqual(verify_production_inputs(sealed,require_seal=True)['files'],2)
        (self.root/'source.SLDASM').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'input changed'):verify_production_inputs(sealed)
    def test_missing_seal_and_changed_code_rejected(self):
        p=self.plan()
        with self.assertRaisesRegex(ValueError,'requires review-production'):verify_production_inputs(p,require_seal=True)
        sealed=seal_production_review(p);sealed['input_review']['code_sha256']={}
        with self.assertRaisesRegex(ValueError,'implementation changed'):verify_production_inputs(sealed)
    def test_outputs_audited_but_never_native_or_manufacturing_approved(self):
        root,data=self.report();r=audit_production(root)
        self.assertTrue(r['execution_evidence_complete'])
        self.assertFalse(r['manufacturing_approved']);self.assertEqual(r['native_acceptance'],'pending_windows_validation')
        self.assertEqual(r['mechanical_findings']['interference_records'],1)
        self.assertNotIn(str(root),json.dumps(r))
    def test_artifact_tamper_and_external_paths_fail(self):
        root,data=self.report();(root/'part.SLDPRT').write_bytes(b'tampered')
        data['artifact_sha256']['C:\\outside.SLDPRT']='b'*64
        (root/'checkpoint.json').write_text(json.dumps(data));r=audit_production(root)
        self.assertFalse(r['execution_evidence_complete'])
        self.assertIn('artifact_checksum_mismatch',r['evidence_errors']);self.assertIn('external_artifact',r['evidence_errors'])
    def test_failed_transaction_export_includes_only_json(self):
        root,data=self.report();data['status']='failed';data['stages']=data['stages'][:2]
        (root/'checkpoint.json').write_text(json.dumps(data))
        result=export_production_acceptance(root,self.root/'export')
        self.assertFalse(result['execution_evidence_complete'])
        with zipfile.ZipFile(result['package']) as z:
            self.assertEqual(set(z.namelist()),{'production-acceptance.json','SHA256.json'})
    def test_missing_drawing_receipt_and_legacy_review_fail_audit(self):
        root,data=self.report();data['drawings']={};data.pop('input_verification')
        (root/'checkpoint.json').write_text(json.dumps(data));r=audit_production(root)
        self.assertIn('missing_drawing_receipts',r['evidence_errors']);self.assertIn('unsealed_inputs',r['evidence_errors'])

if __name__=='__main__':unittest.main()
