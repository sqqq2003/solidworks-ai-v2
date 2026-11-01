"""Fake COM signature/ownership/revision contracts; never native acceptance."""
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from cad_checkpoint import digest_file
from cad_receipts import ReceiptStore, IdempotencyConflict, ReconcileRequired
from modeling_domain.api import run_native_modeling
from modeling_domain.contract import digest
from modeling_domain.native import NativeModelingPort
from sw_feature_calls import solid_revolve
import test_modeling_domain as fixtures


class Variant:
    def __init__(self, tag, value):self.value = value


def variants():
    client = NS(VARIANT=Variant)
    return {'pythoncom': NS(VT_BYREF=0x4000, VT_VARIANT=12, VT_I4=3),
            'win32com': NS(client=client), 'win32com.client': client}


class NativeContractTests(unittest.TestCase):
    def test_native_save3_supplies_byref_long_outputs_and_reads_them_back(self):
        modules=variants();pythoncom=modules['pythoncom'];seen=[]
        class ByRefVariant:
            def __init__(self,tag,value):self.tag=tag;self.value=value
        modules['win32com.client'].VARIANT=ByRefVariant
        def save3(options,errors,warnings):
            seen.append((options,errors,warnings))
            self.assertEqual(options,1)
            self.assertEqual(errors.tag,pythoncom.VT_BYREF|pythoncom.VT_I4)
            self.assertEqual(warnings.tag,pythoncom.VT_BYREF|pythoncom.VT_I4)
            self.assertEqual((errors.value,warnings.value),(0,0))
            errors.value=0;warnings.value=0
            return True
        port=object.__new__(NativeModelingPort)
        port.host=NS(model=NS(Save3=save3));port.guard=lambda:None
        with patch.dict(sys.modules,modules):port._save()
        self.assertEqual(len(seen),1)

    def test_native_save3_reports_returned_error_codes(self):
        port=object.__new__(NativeModelingPort)
        port.host=NS(model=NS(Save3=lambda *_args:(False,17,4)));port.guard=lambda:None
        with patch.dict(sys.modules,variants()):
            with self.assertRaisesRegex(RuntimeError,r'Save3.*errors=17.*warnings=4'):
                port._save()

    def test_revolve_is_twenty_typed_args_with_explicit_merge_and_bounded_radians(self):
        seen = []
        manager = NS(FeatureRevolve2=lambda *a: seen.append(a) or NS(Name='new'))
        solid_revolve(manager, 3.14, merge=False)
        args = seen[0]
        self.assertEqual(len(args), 20)
        self.assertEqual(args[:6], (True, True, False, False, False, False))
        self.assertIs(args[17], False)
        for n in (6, 7, 14):self.assertIs(type(args[n]), int)
        for n in (8, 9, 12, 13, 15, 16):self.assertIs(type(args[n]), float)
        for angle in (-1, 0, 7, float('nan')):
            with self.assertRaises((ValueError, TypeError)):solid_revolve(manager, angle, merge=False)
        with self.assertRaises(TypeError):solid_revolve(manager, 1, merge=1)
        self.assertEqual(len(seen), 1)

    def test_construction_line_flag_and_name_are_read_back_without_axis_guessing(self):
        from ql5050px.editable_features import EditableFeaturesMixin
        segment=NS(ConstructionGeometry=False,GetName=lambda:'Line1')
        feature=NS(Name='old',GetTypeName2=lambda:'ProfileFeature')
        manager=NS(InsertSketch=lambda *_:None,ActiveSketch=object(),CreateLine=lambda *_:segment)
        model=NS(ClearSelection2=lambda *_:None,Extension=NS(),SketchManager=manager,
                 FeatureByPositionReverse=lambda _:feature)
        class Host(EditableFeaturesMixin):
            def guard(self):pass
        host=Host();host.model=model
        plan={'id':'AI_Profile','kind':'sketch','confirmed':True,'evidence':['fixture'],
              'parameters':{'plane':'Front Plane','entities':[{'type':'line','start':[0,0],
              'end':[0,10],'construction':True,'native_name':'Line1'}]}}
        with patch('ql5050px.editable_features.select_by_id',return_value=True), \
             patch('solidworks_generator.ensure_solidworks_typelib',return_value=NS()), \
             patch('solidworks_generator._as_interface',side_effect=lambda module,obj,iface:obj):
            host.create_editable_feature(plan)
            self.assertIs(segment.ConstructionGeometry,True)
            self.assertEqual(feature.Name,'AI_Profile')
            plan['parameters']['entities'][0]['native_name']='Line8'
            with self.assertRaisesRegex(RuntimeError,'segment name differs'):host.create_editable_feature(plan)

    def test_native_revision_detects_unsaved_hand_edits_even_without_bbox_change(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'model.SLDPRT';path.write_bytes(b'baseline')
            model = NS(GetUpdateStamp=lambda: 1, GetSaveFlag=lambda: False,
                       ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default')))
            port = object.__new__(NativeModelingPort)
            port.path = path;port.host = NS(model=model)
            port.guard = lambda: None;port.inventory = lambda: {'features': [], 'bodies': []}
            baseline = port.revision()
            # A clean reopen may have a different transient update stamp.
            model.GetUpdateStamp = lambda: 9
            self.assertEqual(port.revision(), baseline)
            model.GetSaveFlag = lambda: True
            dirty = port.revision();self.assertNotEqual(dirty, baseline)
            model.GetUpdateStamp = lambda: 10
            self.assertNotEqual(port.revision(), dirty)
            model.GetSaveFlag = lambda: False;path.write_bytes(b'hand-saved same envelope')
            self.assertNotEqual(port.revision(), baseline)

    def test_native_guard_refuses_foreign_active_document_before_com_write(self):
        own = NS(GetTitle=lambda: 'work')
        foreign = NS(_oleobj_=NS(QueryInterface=lambda _: 'foreign'))
        own._oleobj_ = NS(QueryInterface=lambda _: 'owned')
        host = NS(guard=lambda: None, model=own, app=NS(ActiveDoc=foreign),
                  lease=NS(owned_docs={'work': NS(handle_id=id(own))}))
        port = object.__new__(NativeModelingPort);port.host=host
        with patch.dict(sys.modules, {'pythoncom': NS(IID_IUnknown=1)}):
            with self.assertRaisesRegex(RuntimeError, 'ActiveDoc'):port.guard()
        host.app.ActiveDoc = own
        port.guard()

    def bodies(self, *, error=0, raw_none=False, valid=True, tuple_result=False):
        seen=[]
        intersection=NS(GetMassProperties=lambda density: [0,0,0,1e-9])
        def boolean(operation, other, output):
            seen.append(('Boolean', operation, other))
            output.value=error
            value=None if raw_none else [intersection]
            return (value,error) if tuple_result else value
        copied_a=NS(Operations2=boolean);copied_b=NS()
        a=NS(Name='AI_A',Check3=NS(Count=0 if valid else 1),
             Copy2=lambda preserve: seen.append(('CopyA',preserve)) or copied_a)
        b=NS(Name='AI_B',Check3=NS(Count=0),
             Copy2=lambda preserve: seen.append(('CopyB',preserve)) or copied_b)
        def closest(left,right,pa,pb):
            self.assertIs(left,a);self.assertIs(right,b)
            pa.value=(0.,0.,0.);pb.value=(0.,0.,0.)
            seen.append(('ClosestDistance',))
            return 0.
        port=object.__new__(NativeModelingPort)
        port.guard=lambda:None;port.host=NS(model=NS(ClosestDistance=closest))
        port._native_bodies=lambda:[a,b]
        return port,seen,copied_b

    def test_boolean_uses_two_copies_explicit_preserve_false_and_real_body_distance(self):
        port,seen,bcopy=self.bodies(tuple_result=True)
        with patch.dict(sys.modules,variants()), \
             patch('solidworks_generator.ensure_solidworks_typelib',return_value=NS()), \
             patch('solidworks_generator._as_interface',side_effect=lambda module,body,iface:body):
            result=port.intersection_on_copies('AI_A','AI_B')
        self.assertEqual(result['intersection_volume_mm3'],1.)
        self.assertEqual(seen,[('ClosestDistance',),('CopyA',False),('CopyB',False),('Boolean',15901,bcopy)])

    def test_boolean_failure_null_and_invalid_body_never_return_zero(self):
        for kwargs in ({'error':1},{'raw_none':True},{'valid':False}):
            with self.subTest(kwargs=kwargs),patch.dict(sys.modules,variants()):
                port,seen,_=self.bodies(**kwargs)
                with self.assertRaises(RuntimeError):port.intersection_on_copies('AI_A','AI_B')
                if kwargs.get('valid') is False:self.assertEqual(seen,[])


class EntryReceiptTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.template=self.root/'empty.prtdot';self.template.write_bytes(b'synthetic template')
        self.db=self.root/'state.sqlite3';self.lease=NS();self.calls=[]
        test=self
        class Port(fixtures.BytePort):
            simulated=False  # fake exercises native entry policy, not acceptance
            def __init__(self,host,originals):
                super().__init__(host.root);self.host=host;self.host.model=object()
                test.calls.append(self)
            def initialize(self):return self.revision()
            def close_for_restore(self,targets):
                super().close_for_restore(targets);self.host.model=None
        self.port_class=Port
        self.binding=NS(evidence=lambda:{'cleanup_status':'left_open_keepalive','ownership':'spawned_pid_and_live_handle',
                                         'attached_existing':False})
        for mocked in [patch('modeling_domain.api.sys.platform','win32'),
                       patch('sw_session.run_on_task_sta',side_effect=lambda fn,**kw:fn()),
                       patch('sw_session.current_lease',return_value=self.lease),
                       patch('cad_reconcile.current_controller_identity',return_value={'pid':123,'creation_filetime':1}),
                       patch('modeling_domain.api.note_owned_process'),
                       patch('sw_owned_launch.owned_solidworks',side_effect=lambda *a,**kw:nullcontext(self.binding)),
                       patch('ql5050px.native_part_host.NativePartHost',side_effect=lambda lease,root,template:NS(root=root)),
                       patch('modeling_domain.native.NativeModelingPort',self.port_class)]:
            mocked.start();self.addCleanup(mocked.stop)

    def call(self,**kwargs):
        plan=fixtures.example()
        args=dict(expected_template_sha256=digest_file(self.template),reviewed_plan_sha256=digest(plan),
                  request_key='modeling-fixture',state_db=self.db)
        args.update(kwargs)
        return run_native_modeling(plan,'SLDWORKS.exe',self.template,self.root/'run',**args)

    def test_real_sqlite_receipt_replays_without_recreating_part_or_observation(self):
        first=self.call();self.assertEqual(first['request_receipt']['status'],'COMPLETED')
        second=self.call();self.assertTrue(second['request_receipt']['replayed'])
        self.assertEqual(len(self.calls),1);self.assertEqual(self.calls[0].writes,2)
        self.assertFalse(second['delivery_accepted']);self.assertTrue(self.lease.close_doc_only)
        self.assertTrue((self.root/'run/observation/observation.json').is_file())
        self.assertEqual(self.template.read_bytes(),b'synthetic template')
        with self.assertRaises(IdempotencyConflict):self.call(camera='front')

    def test_cleanup_disconnect_leaves_durable_quarantine_and_blocks_second_write(self):
        self.binding.evidence=lambda:{'cleanup_status':'left_open_keepalive','cleanup_disconnect':'disconnected'}
        result=self.call()
        self.assertEqual(result['request_receipt']['session_state'],'OUTCOME_UNKNOWN')
        with self.assertRaises(ReconcileRequired):self.call(request_key='different')
        self.assertEqual(len(self.calls),1)

    def test_changed_template_refused_before_admission_and_launch(self):
        with self.assertRaisesRegex(ValueError,'template changed'):self.call(expected_template_sha256='0'*64)
        self.assertEqual(self.calls,[]);self.assertFalse(self.db.exists())

    def test_entry_failure_after_real_file_write_finishes_failed_only_after_restoration(self):
        original=self.port_class.create_feature
        def create(port, feature):
            original(port,feature)
            if feature['kind']=='extrude':raise RuntimeError('saved half build')
        with patch.object(self.port_class,'create_feature',create):
            result=self.call()
        self.assertEqual(result['rollback']['state'],'RESTORED')
        self.assertEqual(result['request_receipt']['status'],'FAILED')
        self.assertEqual(result['request_receipt']['session_state'],'RESOLVED')
        self.assertEqual(self.calls[0].path.read_bytes(),self.calls[0].initial)
        self.assertTrue(self.call()['request_receipt']['replayed'])
        self.assertEqual(len(self.calls),1)

    def test_timeout_quarantines_before_retry_without_launching_another_job(self):
        with patch('sw_session.run_on_task_sta',side_effect=TimeoutError('owned timeout')):
            with self.assertRaises(TimeoutError):self.call()
        self.assertEqual(ReceiptStore(self.db).unresolved()[0]['session_state'],'OUTCOME_UNKNOWN')
        with self.assertRaises(ReconcileRequired):self.call()
        self.assertEqual(self.calls,[])

    def test_linux_entry_refuses_without_creating_files(self):
        with patch('modeling_domain.api.sys.platform','linux'):
            with self.assertRaisesRegex(RuntimeError,'Windows'):self.call()
        self.assertEqual(self.calls,[]);self.assertFalse((self.root/'run').exists())


class AdapterAndCliTests(unittest.TestCase):
    def test_explicit_modeling_adapter_reuses_plan_without_sheet_defaults(self):
        from cad_domains import get_adapter
        adapter=get_adapter('modeling')
        self.assertEqual(adapter.analyze(fixtures.example())['status'],'draft_ready')
        self.assertFalse(adapter.capabilities()['sheet_operations'])
        with self.assertRaises(ValueError):get_adapter('arbitrary_tool')

    def test_sheet_adapter_delegates_actual_existing_synthetic_pipeline(self):
        from cad_domains import get_adapter
        import ezdxf
        from cad_analyzer import analyze_dxf
        from sheet_metal_pipeline import MockSheetMetalPort
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);doc=ezdxf.new('R2010');doc.units=ezdxf.units.MM
            doc.modelspace().add_lwpolyline([(0,0),(100,0),(100,80),(0,80)],close=True)
            source=root/'synthetic.dxf';doc.saveas(source)
            analysis=analyze_dxf(source);adapter=get_adapter('sheet_metal')
            contract=adapter.analyze(analysis,thickness_mm=2,radius_mm=1,angle_degrees=90,
                k_factor=.4,flip_direction=False,units_confirmed=True,bends_confirmed=True)
            result=adapter.run_transaction(contract,analysis,root/'out',MockSheetMetalPort())
            self.assertEqual(result['status'],'simulated_pass')
            self.assertFalse(result['delivery_accepted']);self.assertFalse(result['manufacturing_approved'])
            self.assertTrue((Path(result['output_dir'])/'part.trace.json').is_file())
            with self.assertRaises(ValueError):adapter.run_transaction(fixtures.example(),analysis,root/'bad',MockSheetMetalPort())

    def test_fault_tool_refuses_linux_without_touching_output(self):
        from work.verify_modeling_rollback import main
        with tempfile.TemporaryDirectory() as root,redirect_stdout(io.StringIO()), \
             patch('work.verify_modeling_rollback.sys.platform','linux'):
            output=Path(root)/'run'
            code=main(['plan.json','--sw-exe','SLDWORKS.exe','--template','empty.prtdot',
                       '--expected-template-sha256','0'*64,'--out',str(output),
                       '--request-key','fixture','--fault-after-feature','AI_Boss','--enable-fault-injection'])
            self.assertEqual(code,1);self.assertFalse(output.exists())

    def test_cli_writes_an_actual_analysis_and_refuses_overwriting_it(self):
        from work.modeling import main
        with tempfile.TemporaryDirectory() as root,redirect_stdout(io.StringIO()) as output:
            path=Path(root)/'analysis.json'
            args=['analyze',str(fixtures.ROOT/'examples/modeling-block-v9.json'),'--out',str(path)]
            self.assertEqual(main(args),0)
            self.assertEqual(json.loads(path.read_bytes())['status'],'draft_ready')
            self.assertEqual(main(args),1)


if __name__=='__main__':unittest.main()
