"""Synthetic CAD port, real file rollback/receipts; never native evidence."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock,patch

from cad_receipts import ReceiptStore,ReconcileRequired
from drawing_checkpoint import DrawingModelCheckpoint,protect_drawing_edits
from drawing_review import DrawingEvidence,inspect_drawing
from drawing_run import run_receipted_drawing
from src.a01_next.native_production import A01ProductionDriver
from src.ql5050px.native_drawings import ManufacturingDriver
from src.ql5050px.drawing_verification import annotation_evidence,verify_annotation_evidence
from sw_compat.com_access import read_com_member


class DrawingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.work=self.root/'work';self.work.mkdir()
        self.original=self.root/'user.SLDPRT';self.original.write_bytes(b'baseline')
        self.refs=self.work/'refs';self.refs.mkdir();self.copy=self.refs/'copy.SLDPRT';self.copy.write_bytes(b'baseline')
        self.copies={str(self.original):str(self.copy)}

    def snapshots(self,adapter):
        return {'features':['Boss1'],'bodies':[{'count':1}],'fixture_bytes':self.copy.read_text()}

    def test_drawing_failure_after_dimension_change_restores_copied_model(self):
        driver=A01ProductionDriver(NS(durable_attempt=None),self.work)
        with patch.object(DrawingModelCheckpoint,'assert_closed'), \
             patch.object(DrawingModelCheckpoint,'close_for_restore'), \
             patch.object(DrawingModelCheckpoint,'reopen_snapshot',autospec=True,side_effect=self.snapshots):
            with self.assertRaisesRegex(RuntimeError,'PDF failed'):
                with protect_drawing_edits(driver,[],self.copies):
                    self.copy.write_bytes(b'changed dimensions before drawing')
                    raise RuntimeError('PDF failed')
        self.assertEqual(self.copy.read_bytes(),b'baseline');self.assertEqual(self.original.read_bytes(),b'baseline')
        self.assertEqual(driver.last_drawing_rollback['state'],'RESTORED')
        self.assertFalse(driver._drawing_transaction_active)

    def test_failed_close_preserves_dirty_copy_and_marks_rollback_unconfirmed(self):
        lease=NS(durable_attempt=None,writes_blocked=False)
        driver=A01ProductionDriver(lease,self.work)
        with patch.object(DrawingModelCheckpoint,'assert_closed'), \
             patch.object(DrawingModelCheckpoint,'close_for_restore',side_effect=RuntimeError('foreign active drawing')), \
             patch.object(DrawingModelCheckpoint,'reopen_snapshot',autospec=True,side_effect=self.snapshots):
            with self.assertRaises(RuntimeError):
                with protect_drawing_edits(driver,[],self.copies):
                    self.copy.write_bytes(b'changed');raise RuntimeError('dimension error')
        self.assertEqual(self.copy.read_bytes(),b'changed');self.assertTrue(lease.writes_blocked)
        self.assertEqual(driver.last_drawing_rollback['state'],'ROLLBACK_UNCONFIRMED')

    def test_pdf_failure_keeps_first_page_evidence_and_marks_second_page_failed(self):
        driver=ManufacturingDriver(NS(durable_attempt=None),self.work)
        driver.guard=lambda:None;driver.simulated=True
        tasks=[{'id':str(i),'scale':[1,10],'drawing_model':{'views':[{'id':'front'}]},'node':'A01'} for i in (1,2)]
        def fake_native(plan,receipt,folder,*,_evidence):
            if plan['tasks'][0]['id']=='2':raise RuntimeError('DISP_E_MEMBERNOTFOUND during annotation')
            output=folder/'page1.SLDDRW';output.write_bytes(b'synthetic drawing')
            _evidence.data.update(views=[{'id':'front'}],layout_readback={'sheet_scale':[1,10]},annotation_reopen_verified=True)
            return {'results':[{'path':str(output)}]}
        with patch.object(driver,'_export_manufacturing_unreviewed',side_effect=fake_native):
            with self.assertRaisesRegex(RuntimeError,'MEMBERNOTFOUND'):
                driver.export_manufacturing({'status':'ready_for_native','tasks':tasks},
                    {'documents':{'A01':{'path':str(self.copy)}}},self.work/'drawings')
        folder=self.work/'drawings/evidence'
        self.assertEqual(json.loads((folder/'drawing-0001.json').read_bytes())['state'],'reviewing')
        second=json.loads((folder/'drawing-0002.json').read_bytes())
        self.assertEqual(second['state'],'failed');self.assertTrue(second['member_not_found'])

    def test_recovered_member_not_found_is_still_visible_in_evidence(self):
        e=DrawingEvidence(self.work/'page.json',{'id':'A2','scale':[1,10]},simulated_only=True)
        class Dispatch:
            def GetText(self):raise RuntimeError('DISP_E_MEMBERNOTFOUND')
            def IGetText(self):return 'recovered'
        with e.observe_com():self.assertEqual(read_com_member(Dispatch(),'GetText'),'recovered')
        e.flush();data=json.loads(e.path.read_bytes())
        self.assertTrue(data['member_not_found']);self.assertTrue(data['member_not_found_events'])

    def test_reopened_annotation_identity_and_text_are_checked(self):
        note=NS(GetText=lambda:'SCALE 1:10')
        annotation=NS(GetName=lambda:'Note1',GetType=lambda:6,GetPosition=lambda:(.02,.03,0),GetSpecificAnnotation=lambda:note)
        owner=NS(GetAnnotation=lambda:annotation,GetText=note.GetText)
        expected=annotation_evidence(owner,'note',{'text':'SCALE 1:10'})
        view=NS(GetName2=lambda:'sheet',GetAnnotations=lambda:[annotation],GetNextView=None)
        drawing=NS(GetFirstView=view)
        self.assertTrue(verify_annotation_evidence(drawing,[expected])[0]['reopened'])
        note.GetText=lambda:'SCALE 1:20'
        with self.assertRaisesRegex(RuntimeError,'text differs'):verify_annotation_evidence(drawing,[expected])
        view.GetAnnotations=lambda:[]
        with self.assertRaisesRegex(RuntimeError,'annotation missing'):verify_annotation_evidence(drawing,[expected])

    def test_direct_dimension_call_uses_wrapper_but_active_batch_does_not_double_checkpoint(self):
        driver=A01ProductionDriver(None,self.work)
        with patch.object(driver,'edit_transaction',side_effect=lambda *args:nullcontext()) as wrapper, \
             patch.object(driver,'_apply_mapped_dimensions',return_value=['fixture']) as apply:
            self.assertEqual(driver.apply_mapped_dimensions([],self.copies),['fixture'])
            wrapper.assert_called_once()
            driver._drawing_transaction_active=True
            driver.apply_mapped_dimensions([],self.copies)
            self.assertEqual(wrapper.call_count,1);self.assertEqual(apply.call_count,2)

    def test_restore_closes_only_tracked_owned_drawing_and_model(self):
        from sw_session import OwnedDocument
        model=NS(GetTitle=lambda:'copy',GetPathName=lambda:str(self.copy))
        drawing=NS(GetTitle=lambda:'Drawing1',GetPathName=lambda:'')
        app=NS(ActiveDoc=drawing);lease=NS(owned_docs={name:OwnedDocument(name,id(obj)) for name,obj in [('copy',model),('Drawing1',drawing)]})
        driver=A01ProductionDriver(lease,self.work);driver.guard=lambda:app
        driver._drawing_open_documents={id(model):model,id(drawing):drawing}
        closed=[]
        def close(obj):closed.append(obj);driver._drawing_open_documents.pop(id(obj));app.ActiveDoc=None
        driver.close_document=close
        adapter=DrawingModelCheckpoint(driver,[],self.copies)
        with patch.object(adapter,'assert_closed'):adapter.close_for_restore([str(self.copy)])
        self.assertEqual(closed,[drawing,model])
        app.ActiveDoc=NS(GetTitle=lambda:'user');closed.clear()
        with self.assertRaisesRegex(RuntimeError,'restore refused'):adapter.close_for_restore([str(self.copy)])
        self.assertEqual(closed,[])

    def test_native_fault_tool_refuses_on_linux_without_new_output(self):
        from contextlib import redirect_stdout
        import io
        from work.verify_drawing_rollback import main
        with patch('work.verify_drawing_rollback.sys.platform','linux'),redirect_stdout(io.StringIO()):
            code=main(['request.json','--sw-exe','SLDWORKS.exe','--out',str(self.work/'new'),
                       '--request-key','fixture','--fault-after','pdf','--enable-fault-injection'])
        self.assertEqual(code,1);self.assertFalse((self.work/'new').exists())


class DrawingReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.model=self.root/'model.SLDASM';self.model.write_bytes(b'fake')
        from cad_checkpoint import digest_file
        self.originals={str(self.model):digest_file(self.model)}
        self.db=self.root/'state.sqlite3';self.lease=NS();self.calls=[]
        for mock in [patch('sw_session.run_on_task_sta',side_effect=lambda fn,**kw:fn()),
                     patch('sw_session.current_lease',return_value=self.lease),
                     patch('cad_reconcile.current_controller_identity',return_value={'pid':123,'creation_filetime':1})]:
            mock.start();self.addCleanup(mock.stop)

    def job(self):
        self.calls.append('native_fake')
        return {'status':'native_workflow_executed_pending_review','session':{'cleanup_status':'left_open_keepalive'},'delivery_accepted':False}

    def call(self,payload=None):
        return run_receipted_drawing(self.model,self.originals,payload or {'case':'A2'},self.job,
            timeout=2,task_name='fake-drawing',state_db=self.db)

    def test_completed_drawing_request_replays_result_without_inserting_again(self):
        first=self.call();self.assertEqual(first['request_receipt']['status'],'COMPLETED')
        second=self.call();self.assertTrue(second['request_receipt']['replayed'])
        self.assertEqual(self.calls,['native_fake']);self.assertFalse(second['delivery_accepted'])
        self.assertTrue(self.lease.close_doc_only)

    def test_cleanup_disconnect_does_not_finalize_drawing_as_completed(self):
        self.job=lambda:{'status':'native_workflow_executed_pending_review',
                         'session':{'cleanup_status':'left_open_keepalive','cleanup_disconnect':'COM disconnected'}}
        result=self.call();self.assertEqual(result['request_receipt']['session_state'],'OUTCOME_UNKNOWN')
        with self.assertRaises(ReconcileRequired):self.call({'different':'drawing'})

    def test_timeout_stays_quarantined_after_caller_returns(self):
        with patch('sw_session.run_on_task_sta',side_effect=TimeoutError('fake CAD timeout')):
            with self.assertRaises(TimeoutError):self.call()
        row=ReceiptStore(self.db).unresolved()[0]
        self.assertEqual(row['session_state'],'OUTCOME_UNKNOWN');self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
