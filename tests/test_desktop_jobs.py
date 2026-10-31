"""Headless UI-to-existing-backend contract checks; no CAD execution."""
from pathlib import Path
import tempfile
import unittest
from desktop_jobs import build_desktop_job


class DesktopJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.dxf=root/'input.dxf';self.dxf.write_text('fixture')
        self.values={'kind':'sheet','source':str(self.dxf),'output':str(root/'part.SLDPRT'),
              'sw_exe':'','profile':'1','variant':'0','thickness':'','radius':'','angle':'','k_factor':'',
              'machine':'QL-5050PX','ql_action':'plan','length':'1800','width':'900','height':'1500'}

    def test_analyze_does_not_demand_hidden_bend_parameters(self):
        job=build_desktop_job(self.values,'analyze')
        self.assertEqual(job['action'],'analyze');self.assertNotIn('thickness',job)

    def test_sheet_plan_requires_explicit_job_parameters(self):
        with self.assertRaises(ValueError):build_desktop_job(self.values,'plan')
        self.values.update(thickness='2.5',radius='1',angle='90',k_factor='0.4')
        self.assertEqual(build_desktop_job(self.values,'plan')['k_factor'],.4)

    def test_roller_ignores_sheet_only_fields(self):
        self.values['kind']='roller'
        self.assertEqual(build_desktop_job(self.values,'plan')['variant'],0)

    def test_native_generation_still_requires_review(self):
        self.values['kind']='roller'
        with self.assertRaises(ValueError):build_desktop_job(self.values,'generate',confirmed=False)

    def test_confirmed_native_job_is_bound_to_input_bytes(self):
        from project_workbench import build_command
        exe=Path(self.tmp.name)/'SLDWORKS.exe';exe.touch();self.values.update(kind='roller',sw_exe=str(exe))
        job=build_desktop_job(self.values,'generate',confirmed=True)
        self.assertIn('confirmation_digest',job)
        self.dxf.write_text('changed after review')
        with self.assertRaises(ValueError):build_command(job)

    def test_machine_task_does_not_parse_unrelated_numeric_fields(self):
        config=Path(self.tmp.name)/'project.json';config.write_text('{}')
        self.values.update(kind='ql5050px',source=str(config),output=str(Path(self.tmp.name)/'new'))
        job=build_desktop_job(self.values)
        self.assertEqual(job['kind'],'ql5050px');self.assertNotIn('thickness',job)
