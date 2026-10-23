"""Whole-project job/UI/bundle contracts; no real CAD process or desktop opened."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'src'),str(ROOT/'work')]
from project_workbench import build_command, execute_job, run_batch, write_report, capabilities
from prepare_test_handoff import build_package
from verify_test_handoff import verify
import sw_tool_cli
from turned_part import TurnedPartPlan


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'input; with spaces.dxf'
        self.source.write_text('synthetic command fixture')
        self.exe = self.root/'SLDWORKS.exe'
        self.exe.write_text('fake process never executed')

    def job(self, **kw):
        return {'kind':'sheet','action':'analyze','source':str(self.source),**kw}

    def native(self, **kw):
        return self.job(action='generate',profile=1,thickness=2.5,radius=1,angle=90,k_factor=.25,
            confirmed=True,output=str(self.root/'new.SLDPRT'),sw_exe=str(self.exe),**kw)

    def test_all_part_modes_and_parametric_commands_are_argument_arrays(self):
        for mode in ('sheet','roller','turned'):
            cmd = build_command(self.job(kind=mode))
            self.assertIn(str(self.source),cmd)
            self.assertIn('--analyze-only',cmd)
        cmd = build_command({'kind':'parametric','length':1800,'width':900,'height':1500})
        self.assertIn('src.a01_parametric.cli',cmd)
        self.assertNotIn('--live',cmd)

    def test_native_confirmation_new_path_and_exe_required(self):
        for key,value in (('confirmed',False),('output',str(self.source)),('sw_exe','missing.exe'),('k_factor',float('nan'))):
            job = self.native()
            job[key] = value
            with self.assertRaises(ValueError):
                build_command(job)
        cmd = build_command(self.native())
        self.assertIn('--verify-reopen',cmd)
        self.assertIn('--sw-exe',cmd)

    def test_no_shell_and_exit_zero_alone_is_not_success(self):
        runner = MagicMock(return_value=SimpleNamespace(returncode=0,stdout='unstructured output',stderr=''))
        result = execute_job(self.job(),runner=runner)
        self.assertEqual(result['status'],'failed')
        self.assertFalse(runner.call_args.kwargs['shell'])
        runner.return_value.stdout = json.dumps({'event':'analysis','profiles':[]})
        self.assertEqual(execute_job(self.job(),runner=runner)['status'],'analyzed')
        runner.return_value.stdout = json.dumps({'event':'error','message':'bad geometry'})
        self.assertEqual(execute_job(self.job(),runner=runner)['status'],'failed')

    def test_parametric_pretty_json_remains_review_required(self):
        runner = lambda *a,**kw:SimpleNamespace(returncode=3,stdout=json.dumps({'plan':{'status':'review_required'}},indent=2),stderr='')
        result = execute_job({'kind':'parametric','length':1800,'width':900,'height':1500},runner=runner)
        self.assertEqual(result['status'],'review_required')
        self.assertFalse(result['cad_verified'])
        self.assertEqual(result['events'][0]['kind'],'parametric')

    def test_batch_preflights_all_and_stops_after_native_failure(self):
        execute = MagicMock(return_value={'status':'failed','kind':'sheet'})
        with self.assertRaises(ValueError):
            run_batch([self.native(),self.native()],execute=execute)
        execute.assert_not_called()
        report = run_batch([self.native(),self.job()],execute=execute)
        self.assertEqual(report['results'][1]['status'],'not_run')
        self.assertEqual(execute.call_count,1)

    def test_analysis_failure_does_not_stop_other_offline_jobs(self):
        execute = MagicMock(side_effect=[{'status':'failed'},{'status':'analyzed'}])
        report = run_batch([self.job(),self.job()],execute=execute)
        self.assertEqual(report['counts'],{'analyzed':1,'failed':1})
        self.assertEqual(execute.call_count,2)

    def test_stop_queue_is_not_force_kill(self):
        execute = MagicMock()
        report = run_batch([self.job()],execute=execute,stop_requested=lambda:True)
        self.assertEqual(report['results'][0]['status'],'not_run')
        execute.assert_not_called()

    def test_reports_and_capability_boundaries(self):
        report = {'status':'review_required','results':[{'name':'=1+1','kind':'turned','status':'review_required'}]}
        path = write_report(report,self.root)
        self.assertTrue(path.is_file())
        self.assertIn("'=1+1",path.with_suffix('.csv').read_text(encoding='utf-8-sig'))
        states = {r['id']:r['state'] for r in capabilities()['modules']}
        self.assertIn('scaffold',states['assembly_mates_motion'])
        self.assertIn('pending',states['native_engineering_drawings'])

    def test_turned_plan_entry_never_calls_native_generation(self):
        plan = TurnedPartPlan('horizontal',0,'synthetic',((0,0),(0,8),(120,8),(120,0),(0,0)),(),())
        args = sw_tool_cli.build_parser().parse_args(['--mode','turned','--input',str(self.source),'--plan-only'])
        with patch('sw_tool_cli.analyze_cad_file'),patch('turned_part.discover_turned_parts',return_value=(plan,)),patch('turned_part.generate_turned_part') as native,patch('sw_tool_cli.emit') as emit:
            rc = sw_tool_cli.run_turned(args)
        self.assertIn(rc,(0,3))
        native.assert_not_called()
        self.assertFalse(emit.call_args.kwargs['cad_executed'])
        self.assertIn('feature_plan',emit.call_args.kwargs)

    def test_roller_missing_dimensions_cannot_silently_generate(self):
        from roller_drawing import RollerDrawingVariant
        variant = RollerDrawingVariant('无动力滚筒',1,300,50,None,None,None,None,None,None,'synthetic')
        args = sw_tool_cli.build_parser().parse_args(['--mode','roller','--input',str(self.source),'--out',str(self.root/'r.SLDPRT')])
        with patch('sw_tool_cli.analyze_cad_file',return_value=SimpleNamespace(roller_variants=(variant,))),patch('sw_tool_cli.generate_roller_part') as native,patch('sw_tool_cli.emit') as emit:
            self.assertEqual(sw_tool_cli.run_roller(args),3)
        native.assert_not_called()
        self.assertIn('shaft_diameter_mm',emit.call_args.kwargs['pending'])

    def test_bundle_excludes_cad_and_secrets_and_detects_tamper(self):
        for name,content in [('app.py','print(1)'),('customer.dxf','private'),('credentials.json','secret'),('.env','secret')]:
            (self.root/name).write_text(content)
        listing = 'app.py\0customer.dxf\0credentials.json\0.env\0'
        package = self.root/'bundle.zip'
        with patch('prepare_test_handoff.subprocess.check_output',return_value=listing.encode()):
            result = build_package(self.root,package,'synthetic-test-revision')
        self.assertEqual(result['file_count'],1)
        extract = self.root/'extract'
        with zipfile.ZipFile(package) as bundle:
            self.assertNotIn('customer.dxf',bundle.namelist())
            bundle.extractall(extract)
        self.assertEqual(verify(extract)['status'],'verified')
        (extract/'app.py').write_text('changed')
        self.assertEqual(verify(extract)['status'],'failed')

    def test_app_import_has_no_desktop_or_cad_side_effect(self):
        spec = importlib.util.spec_from_file_location('project_desktop_import_test',ROOT/'app.py')
        module = importlib.util.module_from_spec(spec)
        with patch('subprocess.Popen') as process:
            spec.loader.exec_module(module)
        process.assert_not_called()
        self.assertTrue(callable(module.main))


class SavedPartContractTests(unittest.TestCase):
    def test_nonempty_file_does_not_override_native_save_error(self):
        from part_verification import assert_native_save
        with tempfile.TemporaryDirectory() as folder:
            part = Path(folder)/'test.SLDPRT'
            for contents,code in (('',0),('mock only',2),('mock only',None)):
                part.write_text(contents)
                with self.assertRaises(RuntimeError):
                    assert_native_save(part,code)
            part.write_text('mock native artifact')
            assert_native_save(part,0)

    def test_reopen_checks_dimensions_and_closes_document_on_failure(self):
        from part_verification import verify_saved_part
        with tempfile.TemporaryDirectory() as folder:
            part = Path(folder)/'test.SLDPRT'
            part.write_text('mock artifact, not real CAD')
            lease = MagicMock()
            lease.owned_docs = {}
            lease.note_owned_document.side_effect = lambda title,**kwargs:lease.owned_docs.update({title:object()})
            model = SimpleNamespace(GetTitle=lambda:part.name,GetPathName=lambda:str(part),EditRebuild3=True)
            app = SimpleNamespace(OpenDoc6=lambda *args:model)
            com = SimpleNamespace(CoInitialize=lambda:None,CoUninitialize=lambda:None)
            win = SimpleNamespace(client=SimpleNamespace())
            with patch.dict(sys.modules,{'pythoncom':com,'win32com':win,'win32com.client':win.client}),patch('sw_session.require_model_write',return_value=lease),patch('sw_session.close_owned_document',side_effect=lambda lease,app,title:lease.owned_docs.pop(title,None)) as close,patch('solidworks_generator._connect_task_solidworks',return_value=(app,False)),patch('solidworks_generator.ensure_solidworks_typelib'),patch('solidworks_generator._as_interface',side_effect=lambda m,obj,t:obj),patch('solidworks_generator._body_bounds',return_value=(0,0,0,.12,.016,.016)),patch('solidworks_generator._features',return_value=[]):
                report = verify_saved_part(part,expected_dims_mm=(120,16,16))
                self.assertEqual(report['status'],'reopen_geometry_verified')
                with self.assertRaisesRegex(RuntimeError,'dimensions differ'):
                    verify_saved_part(part,expected_dims_mm=(150,16,16))
            self.assertEqual(close.call_count,2)

    def test_parameter_register_export_preserves_unknown_values(self):
        with tempfile.TemporaryDirectory() as folder:
            report = {'results':[{'name':'a01','kind':'parametric','status':'review_required','events':[
                {'event':'plan','plan':{'values_mm':{'length':1800,'chain_pitch':None},
                 'parameter_register':{'length':{'unit':'mm'},'chain_pitch':{'unit':'mm','confirmation_status':'pending_mapping'}}}}]}]}
            path = write_report(report,folder)
            text = path.with_name(path.stem+'-parameters.csv').read_text(encoding='utf-8-sig')
            self.assertIn('chain_pitch,,mm,pending_mapping',text)
            self.assertIn('length,1800,mm',text)
