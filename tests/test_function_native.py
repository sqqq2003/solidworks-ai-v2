"""Actual temporary files/SQLite, synthetic COM model. No SolidWorks evidence."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from cad_checkpoint import digest_file
from cad_receipts import ReceiptStore, IdempotencyConflict, ReconcileRequired
from modeling_domain.native import NativeModelingPort
from parametric_functions.api import inspect_native_part, execute_edit_workspace
from parametric_functions.native import FunctionModelPort, DimensionExecutionPort
from parametric_functions.workflow import prepare_edit_workspace, approve_edit_workspace
import test_function_modeling as fixtures


class FakeDimension:
    ReadOnly=False;DrivenState=2
    def __init__(self,host,name):self.host=host;self.name=name
    @property
    def SystemValue(self):return self.host.values[self.name]/1000
    def GetType(self):return 0
    def SetSystemValue3(self,value,which,configurations):
        self.host.writes.append((self.name,value,which,configurations))
        self.host.values[self.name]=value*1000;self.host.dirty=True;self.host.stamp+=1
        if self.host.move_protected:self.host.values['D2@Sketch1']+=1
        return 0


class FakeHost:
    def __init__(self,lease,root,template):
        self.lease=lease;self.root=Path(root);self.model=None;self.values={};self.writes=[]
        self.dirty=False;self.stamp=0;self.saved=0;self.fail_save=False;self.move_protected=False;self.foreign=False
        self.app=NS(ActiveDoc=None)
    def reopen(self,path):
        self.path=Path(path);self.values=json.loads(self.path.read_bytes());self.dirty=False
        self.model=NS(Parameter=lambda name:FakeDimension(self,name) if name in self.values else None,
            ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default')),
            EditRebuild3=lambda:True,GetSaveFlag=lambda:self.dirty,GetUpdateStamp=lambda:self.stamp)
        self.app.ActiveDoc=self.model
    def close(self):self.model=None;self.app.ActiveDoc=None
    def rebuild(self):pass


class ByteFunctionPort(FunctionModelPort):
    simulated=False  # Exercise native policy using synthetic COM only.
    hosts=[]
    fail_on_save=False;move_protected=False;foreign=False
    def __init__(self,host,originals):
        super().__init__(host,originals=originals);self.hosts.append(host)
        host.fail_save=self.fail_on_save;host.move_protected=self.move_protected;host.foreign=self.foreign
    def guard(self):
        if getattr(self.host.lease,'durable_write_guard',None):self.host.lease.durable_write_guard()
        if self.host.foreign:raise RuntimeError('foreign ActiveDoc preserved')
    def isolate(self,source,configuration):
        folder=self.host.root/'models';folder.mkdir();self.path=folder/Path(source).name
        shutil.copyfile(source,self.path);self.host.reopen(self.path);self.configuration=configuration
    def inventory(self):
        values=self.host.values
        return {'features':[{'name':'Sketch1','native_type':'ProfileFeature'},{'name':'Boss1','native_type':'Extrude'}],
          'bodies':[{'name':'Body','faces':6,'volume_mm3':values['D1@Sketch1']*values['D2@Sketch1']*10,
                     'bounds_mm':[0,0,0,values['D1@Sketch1'],values['D2@Sketch1'],10]}],
          'bounds_precision':'approximate'}
    def inspect(self,source,configuration,names=()):
        return super().inspect(source,configuration,names or list(self.host.values))
    def _save(self):
        self.guard();self.path.write_text(json.dumps(self.host.values),encoding='utf-8');self.host.dirty=False
        self.host.saved+=1
        if self.host.fail_save and self.host.saved==2:raise RuntimeError('injected after saving changed copy')
    def close_for_restore(self,targets):
        self.guard();self.host.close()
    def assert_closed(self,targets):
        if self.host.model is not None:raise RuntimeError('model still open')


class NativeFlowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.preview,self.mappings,self.inspection=fixtures.fixture(self.root,simulated=False)
        self.source=Path(self.inspection['source_document'])
        self.source.write_text(json.dumps({'D1@Sketch1':40.,'D2@Sketch1':30.}),encoding='utf-8')
        self.inspection['source_sha256']=digest_file(self.source)
        from parametric_functions.workflow import inspect_digest
        self.inspection['inspection_sha256']=inspect_digest(self.inspection)
        self.exe=self.root/'SLDWORKS.exe';self.exe.write_bytes(b'synthetic executable never run')
        self.db=self.root/'state.sqlite3';self.lease=NS(durable_attempt=None)
        ByteFunctionPort.hosts=[];ByteFunctionPort.fail_on_save=False;ByteFunctionPort.move_protected=False;ByteFunctionPort.foreign=False
        self.binding=NS(evidence=lambda:{'cleanup_status':'left_open_keepalive','ownership':'spawned_pid_and_live_handle','attached_existing':False})
        for mocked in [patch('parametric_functions.api.sys.platform','win32'),
                       patch('sw_session.run_on_task_sta',side_effect=lambda fn,**kw:fn()),
                       patch('sw_session.current_lease',return_value=self.lease),
                       patch('cad_reconcile.current_controller_identity',return_value={'pid':123,'creation_filetime':1}),
                       patch('parametric_functions.api.note_owned_process'),
                       patch('parametric_functions.session.modeling_session',side_effect=lambda *a,**kw:nullcontext(self.binding)),
                       patch('ql5050px.native_part_host.NativePartHost',FakeHost),
                       patch('parametric_functions.native.FunctionModelPort',ByteFunctionPort)]:
            mocked.start();self.addCleanup(mocked.stop)
        self.status=prepare_edit_workspace(self.preview,self.mappings,self.inspection,self.root/'review')
        self.approved=approve_edit_workspace(self.root/'review',reviewer='Engineer',expected_review_sha256=self.status['review_sha256'])

    def call(self,**kw):
        options=dict(approval_sha256=self.approved['approval_sha256'],request_key='apply-key',state_db=self.db)
        options.update(kw)
        return execute_edit_workspace(self.root/'review',self.exe,self.root/'output',**options)

    def test_actual_batch_chain_protects_original_and_replays_without_second_native_write(self):
        before=self.source.read_bytes();result=self.call()
        self.assertEqual(result['status'],'native_parameter_edit_pending_review')
        self.assertEqual(result['request_receipt']['status'],'COMPLETED')
        self.assertEqual(ByteFunctionPort.hosts[0].writes,[('D1@Sketch1',.08,3,['Default'])])
        self.assertEqual(json.loads(Path(result['model_path']).read_bytes()),{'D1@Sketch1':80.,'D2@Sketch1':30.})
        self.assertEqual(self.source.read_bytes(),before);self.assertFalse(result['delivery_accepted'])
        replay=self.call();self.assertTrue(replay['request_receipt']['replayed']);self.assertEqual(len(ByteFunctionPort.hosts),1)
        with self.assertRaises(IdempotencyConflict):self.call(session_mode='dedicated')

    def test_failure_after_real_save_restores_checkpoint_bytes_and_resolves_failed_receipt(self):
        ByteFunctionPort.fail_on_save=True
        result=self.call()
        self.assertEqual(result['status'],'failed');self.assertEqual(result['rollback']['state'],'RESTORED')
        self.assertEqual(result['request_receipt']['status'],'FAILED')
        self.assertEqual(result['request_receipt']['session_state'],'RESOLVED')
        target=self.root/'output/models'/self.source.name
        self.assertEqual(json.loads(target.read_bytes()),{'D1@Sketch1':40.,'D2@Sketch1':30.})
        self.assertEqual(self.call()['request_receipt']['replayed'],True)

    def test_native_coupling_that_changes_protected_dimension_rolls_back(self):
        ByteFunctionPort.move_protected=True
        result=self.call();self.assertEqual(result['status'],'failed')
        self.assertEqual(result['rollback']['state'],'RESTORED')
        self.assertIn('dimension differs',result['error'])

    def test_inspection_reads_dimensions_on_copy_and_caches_without_reopening(self):
        result=inspect_native_part(self.source,'Default',self.exe,self.root/'inspect',request_key='inspect-key',state_db=self.db)
        self.assertEqual(result['status'],'inspection_complete')
        self.assertEqual(result['inspection']['dimensions'][0]['value_mm'],40)
        self.assertFalse(result['parameter_write_attempted']);self.assertEqual(ByteFunctionPort.hosts[0].writes,[])
        again=inspect_native_part(self.source,'Default',self.exe,self.root/'inspect',request_key='inspect-key',state_db=self.db)
        self.assertTrue(again['request_receipt']['replayed']);self.assertEqual(len(ByteFunctionPort.hosts),1)

    def test_read_failure_with_verified_cleanup_resolves_failed_and_does_not_block_other_work(self):
        bad=inspect_native_part(self.source,'Default',self.exe,self.root/'bad-read',request_key='bad-read',dimension_names=['Missing@Sketch1'],state_db=self.db)
        self.assertEqual(bad['request_receipt']['status'],'FAILED')
        self.assertEqual(bad['request_receipt']['session_state'],'RESOLVED')
        self.assertEqual(self.call()['status'],'native_parameter_edit_pending_review')

    def test_changed_source_or_simulated_snapshot_never_reaches_native(self):
        self.source.write_bytes(b'hand-edited source')
        with self.assertRaises(ValueError):self.call()
        self.assertEqual(ByteFunctionPort.hosts,[])

    def test_cleanup_disconnect_keeps_ledger_unresolved_and_blocks_new_request(self):
        self.binding.evidence=lambda:{'cleanup_status':'left_open_keepalive','cleanup_disconnect':'COM gone'}
        result=self.call();self.assertEqual(result['request_receipt']['session_state'],'OUTCOME_UNKNOWN')
        with self.assertRaises(ReconcileRequired):self.call(request_key='other')

    def test_linux_refusal_creates_no_native_directory_or_ledger(self):
        with patch('parametric_functions.api.sys.platform','linux'):
            with self.assertRaisesRegex(RuntimeError,'Windows'):self.call()
        self.assertFalse(self.db.exists());self.assertFalse((self.root/'output').exists())


class IdleSessionTests(unittest.TestCase):
    def test_foreign_documents_never_close_or_become_owned(self):
        from parametric_functions.session import IdleBinding
        from sw_session import SessionOwnershipError
        lease=NS(owned_docs={},foreign_titles=set(),writes_blocked=False)
        app=NS(CloseDoc=lambda title:self.fail('unknown document closed'))
        lifetime=NS(pid=123)
        binding=IdleBinding(lifetime,app,lambda app:123,lambda app:['customer.SLDASM'])
        binding._read_connection_or_rebind=lambda lease:(True,123)
        with patch('parametric_functions.session._snapshot_open_documents',return_value=([{'title':'customer.SLDASM','path':'C:/Customer.SLDASM'}],[])):
            with self.assertRaises(SessionOwnershipError):binding.validate(lease)
        self.assertTrue(lease.writes_blocked);self.assertFalse(lease.owned_docs)


if __name__=='__main__':unittest.main()
