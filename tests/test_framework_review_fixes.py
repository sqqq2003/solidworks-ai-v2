"""Focused regression contracts; authored but not run in development batch."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'),str(ROOT/'work')]
from project_workbench import build_command, confirm_job, execute_job, run_batch
from part_verification import solid_inventory
from prepare_test_handoff import collect


class FrameworkReviewFixes(unittest.TestCase):
    def test_confirmation_invalidated_by_input_and_option_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            source,exe = Path(folder)/'input.dxf',Path(folder)/'SLDWORKS.exe'
            source.write_text('first version')
            exe.write_text('never executed')
            job = confirm_job({'kind':'sheet','action':'generate','source':str(source),
                'output':str(Path(folder)/'part.SLDPRT'),'sw_exe':str(exe),
                'profile':1,'thickness':2,'radius':1,'angle':90,'k_factor':.4})
            build_command(job)
            with self.assertRaisesRegex(ValueError,'changed since review'):
                build_command({**job,'flip':True})
            source.write_text('replacement drawing')
            with self.assertRaisesRegex(ValueError,'changed since review'):
                build_command(job)

    def test_ql_never_uses_gtzx_default(self):
        with self.assertRaisesRegex(ValueError,'machine=GT-ZX'):
            build_command({'kind':'parametric','length':1800,'width':900,'height':1500})
        command = build_command({'kind':'parametric','machine':'QL-5050PX','length':1800,'width':900,'height':1500})
        self.assertTrue(any(arg.endswith('work/ql5050px.py') for arg in command))
        self.assertNotIn('src.a01_parametric.cli',command)

    def test_all_bodies_contribute_to_union(self):
        bodies = [SimpleNamespace(GetFaces=lambda:[SimpleNamespace(GetBox=lambda:(0,0,0,.01,.01,.01))]),
                  SimpleNamespace(GetFaces=lambda:[SimpleNamespace(GetBox=lambda:(.02,0,0,.04,.02,.02))])]
        part = SimpleNamespace(GetBodies2=lambda *_:bodies)
        sw = SimpleNamespace(SW_BODY_TYPE_SOLID=0,_as_interface=lambda module,obj,name:obj)
        bounds,inventory = solid_inventory(part,sw,None)
        self.assertEqual(bounds,[0,0,0,40,20,20])
        self.assertEqual(len(inventory),2)

    def test_timeout_report_and_queue_stop(self):
        job = {'kind':'parametric','machine':'GT-ZX','length':1800,'width':900,'height':1500}
        def expire(*args,**kwargs):
            raise subprocess.TimeoutExpired(args[0],kwargs['timeout'])
        result = execute_job(job,runner=expire)
        self.assertEqual(result['status'],'timed_out')
        self.assertTrue(result['worker_may_be_running'])
        report = run_batch([job,job],execute=lambda _:result)
        self.assertEqual(report['status'],'failed')
        self.assertEqual(report['results'][1]['status'],'not_run')

    def test_packager_requests_tracked_only_and_rejects_customer_json(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('app.py','customer_params.json','notes.txt'):
                (root/name).write_text('fixture')
            with patch('prepare_test_handoff.subprocess.check_output',return_value=b'app.py\0customer_params.json\0notes.txt\0') as listing:
                self.assertEqual(collect(root),[Path('app.py')])
                args = listing.call_args.args[0]
                self.assertIn('--cached',args)
                self.assertNotIn('--others',args)
