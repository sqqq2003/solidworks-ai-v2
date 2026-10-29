"""Real JSON/file/decision publication with synthetic drawing evidence only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io,json
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from drawing_review import (CHECKLIST,DrawingEvidence,atomic_json,inspect_drawing,
                            inspect_drawing_batch,review_drawing,export_visual_review)
from cad_receipts import ReceiptStore
from work.drawing_review import main


class VisualReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.model=self.root/'model.SLDPRT';self.model.write_bytes(b'synthetic model')
        self.drawing=self.root/'page.SLDDRW';self.drawing.write_bytes(b'synthetic drawing')
        self.pdf=self.root/'page.pdf';self.pdf.write_bytes(b'synthetic PDF; not a CAD test')
        self.task={'id':'D4-A2-1-10','scale':[1,10], 'drawing_model':{'views':[{'id':'front'}]},'annotations':[]}
        self.checklist={key:True for key in CHECKLIST}

    def evidence(self,**kwargs):
        e=DrawingEvidence(self.root/'evidence/page.json',self.task,model_path=self.model,**kwargs)
        e.data.update(views=[{'id':'front','scale':.1}],layout_readback={'sheet_scale':[1,10]},annotation_reopen_verified=True)
        e.data['pdf_validation']={'parsed':True,'pages':1} # Explicit fake port result; native PDF parser has separate tests.
        e.artifact('slddrw',self.drawing)
        return e

    def accept(self,path,**kwargs):
        current=inspect_drawing(path)
        return review_drawing(path,reviewer='Human fixture reviewer',expected_sha256=current['evidence_sha256'],
                              decision='accepted',checklist=self.checklist,**kwargs)

    def test_save_reopen_only_enters_reviewing_until_named_visual_acceptance(self):
        e=self.evidence();report=e.finish()
        self.assertEqual(report['state'],'reviewing');self.assertFalse(report['delivery_accepted'])
        accepted=self.accept(e.path)
        self.assertEqual(accepted['state'],'accepted');self.assertTrue(accepted['delivery_accepted'])
        self.assertFalse(accepted['manufacturing_approved'])

    def test_partial_model_visual_acceptance_never_becomes_production_delivery(self):
        e=self.evidence(partial_model_test=True);e.finish();report=self.accept(e.path)
        self.assertTrue(report['visual_accepted']);self.assertFalse(report['delivery_accepted'])

    def test_missing_pdf_cannot_reach_visual_gate(self):
        e=self.evidence(required_artifacts=('slddrw','pdf'));e.finish()
        with self.assertRaisesRegex(ValueError,'cannot be accepted'):self.accept(e.path)
        e.artifact('pdf',self.pdf);e.finish();self.assertTrue(self.accept(e.path)['delivery_accepted'])

    def test_failed_pdf_or_member_failure_cannot_be_accepted(self):
        e=self.evidence();e.finish();e.fail(RuntimeError('DISP_E_MEMBERNOTFOUND'))
        report=inspect_drawing(e.path)
        self.assertEqual(report['state'],'failed');self.assertTrue(report['member_not_found'])
        with self.assertRaises(ValueError):self.accept(e.path)

    def test_named_reviewer_and_all_four_explicit_checks_are_required(self):
        e=self.evidence();e.finish();sha=inspect_drawing(e.path)['evidence_sha256']
        for name,check in [('',self.checklist),('Human',{}),('Human',{**self.checklist,'scale':1})]:
            with self.assertRaises(ValueError):
                review_drawing(e.path,reviewer=name,expected_sha256=sha,decision='accepted',checklist=check)

    def test_changed_drawing_pdf_or_model_invalidates_previous_acceptance(self):
        e=self.evidence(required_artifacts=('slddrw','pdf'));e.artifact('pdf',self.pdf);e.finish();self.accept(e.path)
        for artifact in (self.model,self.drawing,self.pdf):
            before=artifact.read_bytes();artifact.write_bytes(before+b'changed')
            report=inspect_drawing(e.path)
            self.assertFalse(report['visual_accepted']);self.assertFalse(report['delivery_accepted'])
            self.assertIn('source_or_artifact_changed',report['issues']);artifact.write_bytes(before)

    def test_new_evidence_bytes_require_new_decision_and_reject_stale_review(self):
        e=self.evidence();e.finish();old=inspect_drawing(e.path)['evidence_sha256'];self.accept(e.path)
        e.data['member_not_found']=True;e.flush()
        self.assertEqual(inspect_drawing(e.path)['state'],'reviewing')
        with self.assertRaisesRegex(ValueError,'changed since review'):
            review_drawing(e.path,reviewer='Human',expected_sha256=old,decision='accepted',checklist=self.checklist)

    def test_crash_before_atomic_replace_leaves_previous_complete_json(self):
        e=self.evidence();before=e.path.read_bytes()
        with patch('drawing_review.os.replace',side_effect=OSError('simulated interrupted publish')):
            with self.assertRaises(OSError):e.finish()
        self.assertEqual(e.path.read_bytes(),before);json.loads(e.path.read_bytes())
        self.assertFalse(inspect_drawing(e.path)['delivery_accepted'])
        self.assertEqual(list(e.path.parent.glob('.page.json-*')),[])

    def test_competing_accept_reject_decisions_publish_only_one_full_record(self):
        e=self.evidence();e.finish();sha=inspect_drawing(e.path)['evidence_sha256']
        def decide(value):
            try:
                review_drawing(e.path,reviewer=value,expected_sha256=sha,decision=value,
                               checklist=self.checklist,notes='human review reason')
                return 'published'
            except FileExistsError:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(decide,['accepted','rejected']))
        self.assertEqual(sorted(results),['conflict','published'])
        records=list((e.path.parent/'visual-reviews').glob('*.json'));self.assertEqual(len(records),1)
        self.assertIn(json.loads(records[0].read_bytes())['decision'],{'accepted','rejected'})

    def test_unresolved_native_request_blocks_accepting_a_complete_page(self):
        e=self.evidence();store=ReceiptStore(self.root/'state.sqlite3')
        row=store.begin(self.model,'r1',{'fixture':True})
        e.data['request_receipt']={'database':str(store.path),'key':row['key']};e.finish()
        with self.assertRaisesRegex(ValueError,'native_request_unresolved'):self.accept(e.path)
        store.finish(row['key'],row['owner'],{'status':'completed'},succeeded=True)
        self.assertTrue(self.accept(e.path)['delivery_accepted'])

    def test_incomplete_or_simulated_records_never_pass_even_with_complete_flag(self):
        e=self.evidence(simulated_only=True);e.finish()
        with self.assertRaisesRegex(ValueError,'simulated'):self.accept(e.path)
        e.data.update(simulated_only=False,complete=True,technical_status='saved_reopened',views=[]);e.flush()
        with self.assertRaisesRegex(ValueError,'readback_incomplete'):self.accept(e.path)

    def test_batch_missing_second_page_does_not_report_complete_delivery(self):
        e=self.evidence();e.finish();self.accept(e.path)
        atomic_json(self.root/'drawing-index.json',{'schema_version':1,'pages':[
            {'evidence':'evidence/page.json'},{'evidence':'evidence/missing.json'}]})
        batch=inspect_drawing_batch(self.root)
        self.assertFalse(batch['delivery_accepted']);self.assertIn('page_evidence_missing_or_invalid',batch['issues'])

    def test_review_cli_requires_explicit_decision_and_returns_pending_for_inspect(self):
        e=self.evidence();e.finish();stream=io.StringIO()
        with redirect_stdout(stream):code=main(['inspect',str(e.path)])
        self.assertEqual(code,3);self.assertFalse(json.loads(stream.getvalue())['delivery_accepted'])
        checklist=self.root/'checks.json';checklist.write_text(json.dumps(self.checklist))
        with redirect_stdout(io.StringIO()):code=main(['review',str(e.path),'--reviewer','Human',
            '--evidence-sha256',inspect_drawing(e.path)['evidence_sha256'],'--decision','accepted','--checklist',str(checklist)])
        self.assertEqual(code,0)

    def test_redacted_export_and_trial_ui_preserve_visual_vs_delivery_boundary(self):
        from drawing_trial_app import inspect_trial_result
        e=self.evidence(partial_model_test=True);e.finish();self.accept(e.path)
        atomic_json(self.root/'drawing-index.json',{'schema_version':1,'pages':[{'evidence':'evidence/page.json'}]})
        result={'mode':'explicit_partial_model_test','status':'completed_partial_model_trial',
                'cells':[{'status':'pass_pending_visual','drawing':{'results':[{'drawing_evidence':str(e.path)}]}}]}
        atomic_json(self.root/'result.json',result)
        ui=inspect_trial_result(0,self.root)
        self.assertEqual(ui['acceptance_state'],'accepted');self.assertTrue(ui['visual_accepted'])
        self.assertFalse(ui['delivery_accepted'])
        exported=export_visual_review(self.root,self.root/'export.json',source_revision='a'*40)
        self.assertNotIn(str(self.root),json.dumps(exported));self.assertFalse(exported['delivery_accepted'])


if __name__=='__main__':unittest.main()
