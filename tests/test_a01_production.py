"""Synthetic records and fake drivers only; no native CAD opened."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from src.a01_next.production import prepare_request,execute_request,sha
from src.a01_next.native_production import A01ProductionDriver


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.feature_patch=patch('src.a01_next.native_production.find_named_feature',
                                 side_effect=lambda model,name:model.FeatureByName(name))
        self.feature_patch.start();self.addCleanup(self.feature_patch.stop)
        self.root=Path(self.temp.name);self.source=self.root/'source.SLDASM';self.part=self.root/'part.SLDPRT'
        self.source.write_bytes(b'synthetic assembly');self.part.write_bytes(b'synthetic part')
        row=dict(parameter='frame.length',document=str(self.part),configuration='Default',feature='Sketch1',
                 dimension='D1@Sketch1',unit='mm',source='reviewed synthetic fixture',allowed_range=[1,2000],status='confirmed')
        self.request=dict(schema_version=1,source_assembly=str(self.source),source_sha256=sha(self.source),
            configuration='Default',document_sha256={str(self.part):sha(self.part)},
            mapping=dict(schema_version=1,parameters=[row]),values={'frame.length':1800})

    def test_planning_is_readonly_and_identity_bound(self):
        p=prepare_request(self.request)
        self.assertEqual(p['status'],'ready_for_native');self.assertFalse(p['cad_executed'])
        self.assertEqual(self.part.read_bytes(),b'synthetic part')
        self.part.write_bytes(b'changed')
        with self.assertRaises(ValueError):prepare_request(self.request)

    def test_unknown_unconfirmed_protected_and_out_of_range_refused(self):
        for field,value in [('status','unconfirmed'),('component_kind','purchased'),('dimension','D1@Other'),('unit','count')]:
            r=copy.deepcopy(self.request);r['mapping']['parameters'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):prepare_request(r)
        self.request['values']['frame.length']=float('nan')
        with self.assertRaises(ValueError):prepare_request(self.request)

    def test_source_hash_mismatch_refused_before_driver(self):
        self.request['source_sha256']='0'*64;driver=MagicMock()
        with self.assertRaises(ValueError):execute_request(self.request,driver,self.root/'out')
        driver.pack_and_go.assert_not_called()

    def test_copy_mapping_mates_checks_order_and_no_release_claim(self):
        driver=MagicMock();driver.pack_and_go.return_value='copy.SLDASM'
        driver.receipt={'events':[{'copies':{str(self.part):'copy.SLDPRT'}}]}
        driver.apply_mapped_dimensions.return_value=[];driver.apply_persistent_mates.return_value=[]
        driver.inspect_native.return_value={'interference_count':0}
        r=execute_request(self.request,driver,self.root/'out')
        self.assertFalse(r['cad_release_approved']);self.assertEqual(r['engineering_acceptance'],'unverified')
        driver.export_manufacturing.assert_not_called()
        self.assertEqual([c[0] for c in driver.method_calls],['pack_and_go','apply_mapped_dimensions','apply_persistent_mates','inspect_native'])

    def test_interference_blocks_drawing(self):
        driver=MagicMock();driver.receipt={'events':[{'copies':{}}]}
        driver.inspect_native.return_value={'interference_count':1}
        with self.assertRaises(RuntimeError):execute_request(self.request,driver,self.root/'out')
        driver.export_manufacturing.assert_not_called()

    def test_mate_missing_registry_refused(self):
        self.request['mates']=[dict(id='mate1',type='distance',references=['a','b'],alignment=0,distance_mm=10)]
        with self.assertRaises(ValueError):prepare_request(self.request)

    def test_persistent_reference_context_mismatch_refused(self):
        self.request['references']=dict(schema_version=1,references=[dict(id=name,document_sha256='0'*64,
            configuration='Default',component_path=name,entity_type='face',persistent_reference_base64=token)
            for name,token in [('a','AQID'),('b','BAUG')]])
        self.request['mates']=[dict(id='mate1',type='distance',references=['a','b'],alignment=0,distance_mm=10)]
        with self.assertRaises(ValueError):prepare_request(self.request)

    def test_dimension_api_units_and_reopen_readback(self):
        model=MagicMock();dimension=MagicMock();dimension.SystemValue=1.8
        model.ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default'))
        dimension.SetSystemValue3.return_value=0;model.Parameter.return_value=dimension
        model.Save3.return_value=(True,0,0)
        driver=A01ProductionDriver(None,self.root)
        driver.guard=MagicMock();driver.verify_references=MagicMock()
        driver.open_document=MagicMock(return_value=model);driver.close_document=MagicMock()
        edits=prepare_request(self.request)['edits']
        result=driver.apply_mapped_dimensions(edits,{str(self.part):str(self.root/'copy.SLDPRT')})
        dimension.SetSystemValue3.assert_called_once_with(1.8,1,None)
        self.assertTrue(result[0]['reopened'])

    def test_configuration_checks_readback_without_redundant_switch(self):
        from src.a01_next.native_production import activate_configuration
        model=MagicMock();config=NS(Name='默认');model.ConfigurationManager=NS(ActiveConfiguration=config)
        model.ShowConfiguration2.return_value=False
        activate_configuration(model,'默认')
        model.ShowConfiguration2.assert_not_called()
        with self.assertRaisesRegex(RuntimeError,'switch failed'):
            activate_configuration(model,'missing')
        model.ShowConfiguration2.return_value=True
        with self.assertRaisesRegex(RuntimeError,'readback mismatch'):
            activate_configuration(model,'missing')

    def test_feature_lookup_casts_to_the_correct_document_interface(self):
        self.feature_patch.stop()
        from src.a01_next.native_production import find_named_feature
        typed=MagicMock();feature=object();typed.FeatureByName.return_value=feature
        with patch('solidworks_generator.ensure_solidworks_typelib',return_value='library'), \
             patch('solidworks_generator._as_interface',return_value=typed) as cast:
            for kind,expected in [(1,'IPartDoc'),(2,'IAssemblyDoc')]:
                model=NS(GetType=kind)
                self.assertIs(find_named_feature(model,'NamedFeature'),feature)
                cast.assert_called_with('library',model,expected)
            with self.assertRaisesRegex(RuntimeError,'part or assembly'):
                find_named_feature(NS(GetType=3),'NamedFeature')

    def test_missing_dimension_preflight_never_writes(self):
        model=MagicMock();model.Parameter.return_value=None
        model.ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default'))
        driver=A01ProductionDriver(None,self.root);driver.guard=MagicMock()
        driver.open_document=MagicMock(return_value=model);driver.close_document=MagicMock()
        with self.assertRaises(RuntimeError):driver.apply_mapped_dimensions(prepare_request(self.request)['edits'],{str(self.part):str(self.root/'copy.SLDPRT')})
        model.Save3.assert_not_called()

    def test_dimension_journal_correlates_before_write_and_reopen(self):
        class Dimension:
            SystemValue=1.2
            def SetSystemValue3(self,value,scope,configs):
                # Native regression: specific-config writes returned success
                # but left the dimension unchanged on the real tube part.
                if scope == 1 and configs is None:
                    self.SystemValue=value
                return 0
        dimension=Dimension();model=MagicMock();model.Parameter.return_value=dimension
        model.ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default'))
        model.Save3.return_value=(True,0,0)
        driver=A01ProductionDriver(None,self.root);driver.guard=MagicMock();driver.verify_references=MagicMock()
        driver.open_document=MagicMock(return_value=model);driver.close_document=MagicMock()
        journal=MagicMock()
        with patch('app_logging.get_journal',return_value=journal):
            result=driver.apply_mapped_dimensions(prepare_request(self.request)['edits'],
                {str(self.part):str(self.root/'copy.SLDPRT')})
        self.assertEqual(result[0]['before_value_si'],1.2)
        self.assertEqual(result[0]['after_value_si'],1.8)
        self.assertEqual(result[0]['reopened_value_si'],1.8)
        self.assertFalse(result[0]['production_approved'])
        entries=[(c.args[0],c.kwargs.get('step_id')) for c in journal.record.call_args_list]
        self.assertEqual([x[0] for x in entries],['dimension_change_started','dimension_change_readback','dimension_change_reopened'])
        self.assertEqual(len({x[1] for x in entries}),1)

    def test_observed_write_forces_body_rebuild_and_refuses_rebuild_failure(self):
        edit=prepare_request(self.request)['edits'][0]
        copy=self.root/'observed.SLDPRT';copy.write_bytes(b'work copy')
        parameter=edit['parameter']
        contract={'confirmed':True,'confirmed_by':'synthetic trial',
                  'source_sha256':sha(self.part),
                  'dimensions_mm':{parameter:edit['dimension']},
                  'checks':[{'field':'dimension:'+parameter,'mode':'target',
                             'unit':'mm','value':edit['value'],'tolerance':.001}]}
        model=MagicMock();model.ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default'))
        model.Parameter.return_value.SetSystemValue3.return_value=0
        driver=A01ProductionDriver(None,self.root);driver.guard=MagicMock()
        def transaction(_driver,**kwargs):
            kwargs['apply_change'](model)
            return {'status':'synthetic_callback_only'}
        with patch('owned_part_transaction.change_owned_part',side_effect=transaction):
            model.ForceRebuild3.return_value=True
            driver.apply_mapped_dimensions_observed([edit],{str(self.part):str(copy)},{parameter:contract})
            model.ForceRebuild3.assert_called_once_with(False)
            model.ForceRebuild3.return_value=False
            with self.assertRaisesRegex(RuntimeError,'force rebuild failed'):
                driver.apply_mapped_dimensions_observed([edit],{str(self.part):str(copy)},{parameter:contract})
        model.Save3.assert_not_called()

    def test_nonfinite_before_dimension_is_refused_before_write(self):
        model=MagicMock();dimension=MagicMock();dimension.SystemValue=float('nan');model.Parameter.return_value=dimension
        model.ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default'))
        driver=A01ProductionDriver(None,self.root);driver.guard=MagicMock()
        driver.open_document=MagicMock(return_value=model);driver.close_document=MagicMock()
        with self.assertRaisesRegex(RuntimeError,'before value'):
            driver.apply_mapped_dimensions(prepare_request(self.request)['edits'],{str(self.part):str(self.root/'copy.SLDPRT')})
        dimension.SetSystemValue3.assert_not_called();model.Save3.assert_not_called()

    def test_all_before_values_are_checked_before_first_write(self):
        model=MagicMock();first=MagicMock();first.SystemValue=1.2
        model.ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default'))
        second=MagicMock();second.SystemValue=float('nan')
        model.Parameter.side_effect=[first,second]
        driver=A01ProductionDriver(None,self.root);driver.guard=MagicMock()
        driver.open_document=MagicMock(return_value=model);driver.close_document=MagicMock()
        first_edit=prepare_request(self.request)['edits'][0]
        second_edit={**first_edit,'parameter':'frame.height','dimension':'D2@Sketch1'}
        with self.assertRaisesRegex(RuntimeError,'before value'):
            driver.apply_mapped_dimensions([first_edit,second_edit],{str(self.part):str(self.root/'copy.SLDPRT')})
        first.SetSystemValue3.assert_not_called();second.SetSystemValue3.assert_not_called()

    def test_reopen_disconnect_records_failure_without_faking_success(self):
        model=MagicMock();dimension=MagicMock();dimension.SystemValue=1.8
        model.ConfigurationManager=NS(ActiveConfiguration=NS(Name='Default'))
        dimension.SetSystemValue3.return_value=0;model.Parameter.return_value=dimension
        model.Save3.return_value=(True,0,0)
        driver=A01ProductionDriver(None,self.root);driver.guard=MagicMock();driver.verify_references=MagicMock()
        driver.open_document=MagicMock(side_effect=[model,RuntimeError('COM disconnected')]);driver.close_document=MagicMock()
        journal=MagicMock()
        with patch('app_logging.get_journal',return_value=journal):
            with self.assertRaisesRegex(RuntimeError,'COM disconnected'):
                driver.apply_mapped_dimensions(prepare_request(self.request)['edits'],{str(self.part):str(self.root/'copy.SLDPRT')})
        journal.exception.assert_called_once()
        self.assertEqual(journal.exception.call_args.args[0],'dimension_change_reopen_failed')
        self.assertFalse(any(c.args[0]=='dimension_change_reopened' for c in journal.record.call_args_list))

    def test_native_mate_uses_mark_one_and_equal_distance_limits(self):
        driver=A01ProductionDriver(None,self.root);driver.guard=MagicMock()
        model=MagicMock();model.FeatureByName.return_value=None
        model.Extension.GetObjectByPersistReference3.return_value=MagicMock()
        driver.open_document=MagicMock(return_value=model);driver.close_document=MagicMock()
        driver.verify_references=MagicMock();driver._save=MagicMock()
        assembly=MagicMock();feature=MagicMock()
        registry={'references':[dict(id=n,entity_type='face',persistent_reference_base64=t)
                                for n,t in [('a','AQID'),('b','BAUG')]]}
        mate=dict(id='distance1',type='distance',alignment=0,references=['a','b'],distance_mm=10)
        def cast(lib,obj,kind):
            return assembly if kind=='IAssemblyDoc' else feature if kind=='IFeature' else obj
        with patch.dict(sys.modules,{'pythoncom':NS(VT_ARRAY=1,VT_UI1=2,VT_BYREF=4,VT_I4=8),
                'win32com.client':NS(VARIANT=lambda tag,value:NS(value=value))}), \
             patch('solidworks_generator._as_interface',side_effect=cast), \
             patch('solidworks_generator.ensure_solidworks_typelib',return_value=None), \
             patch('src.a01_next.native_production.feature_error',return_value=0):
            result=driver.apply_persistent_mates(self.root/'copy.SLDASM','Default',[mate],registry)
        args=assembly.AddMate5.call_args.args
        self.assertEqual(args[3:6],(.01,.01,.01))
        self.assertEqual(len(args),15)
        self.assertEqual(feature.Name,'distance1')
        self.assertEqual(result[0]['feature_error'],0)
        driver._save.assert_called_once_with(model)

    def test_native_feature_warning_return_is_not_error_code(self):
        from src.a01_next.native_production import feature_error
        f=MagicMock();f.GetErrorCode2.return_value=(0,True)
        with patch.dict(sys.modules,{'pythoncom':NS(VT_BYREF=1,VT_BOOL=2),
                'win32com.client':NS(VARIANT=lambda tag,value:NS(value=value))}):
            self.assertEqual(feature_error(f),0)

    def test_drawing_template_projection_is_checked_before_views(self):
        from src.ql5050px.native_drawings import ManufacturingDriver
        driver=ManufacturingDriver(MagicMock(),self.root)
        app=MagicMock();drawing=MagicMock()
        drawing.GetCurrentSheet.return_value.GetProperties2.return_value=[12,0,1,1,False,.42,.297,False]
        app.NewDocument.return_value=drawing
        driver.guard=MagicMock();driver.app=app;driver.require_isolated_model=MagicMock()
        driver.open_document=MagicMock(return_value=MagicMock())
        template=self.root/'fixture.drwdot';template.write_bytes(b'synthetic template')
        task=dict(node='A01',template=str(template),width_mm=420,height_mm=297,projection='first_angle')
        with self.assertRaisesRegex(RuntimeError,'first-angle'):
            driver.export_manufacturing(dict(status='ready_for_native',tasks=[task]),
                {'documents':{'A01':{'path':'copy.SLDASM','configuration':'Default'}}},self.root/'drawings')
        drawing.CreateDrawViewFromModelView3.assert_not_called()
