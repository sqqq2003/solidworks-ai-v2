"""Actual offline cross-module integration; no Windows COM is used."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unified_project import build_release
from project_workbench import execute_job

ROOT=Path(__file__).resolve().parents[1]

class UnifiedProjectTests(unittest.TestCase):
    def setUp(self):
        self.request=json.loads((ROOT/'examples/unified-project.json').read_text(encoding='utf-8'))
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name)/'release'

    def test_actual_offline_end_to_end(self):
        with patch('sw_owned_launch.owned_solidworks',side_effect=AssertionError('offline must not spawn CAD')):
            report=build_release(self.request,self.out)
        self.assertEqual(report['status'],'review_required')
        stages=report['stages'];chain=stages['engineering']['modules']['dimensions']
        self.assertEqual(chain['after_mm']['barrel_length'],stages['roller']['resolved_mm']['barrel_length'])
        self.assertEqual(chain['after_mm']['overall_length'],800)
        self.assertEqual(chain['before_mm']['left_projection'],chain['after_mm']['left_projection'])
        self.assertFalse(report['cad_executed'])
        platform=json.loads((self.out/'platform/request.json').read_text())
        self.assertEqual(platform['assembly_plan'],stages['machine']['machine_plan']['assembly_plan'])
        self.assertEqual(platform['components'],stages['machine']['machine_plan']['drawing_plan']['bom'])
        self.assertTrue((self.out/'gork-unified.zip').is_file())

    def test_manifest_hashes(self):
        build_release(self.request,self.out)
        manifest=json.loads((self.out/'HANDOFF.json').read_text())
        self.assertEqual(manifest['code_sha256']['src/unified_project.py'],hashlib.sha256((ROOT/'src/unified_project.py').read_bytes()).hexdigest())
        for name,sha in manifest['files'].items():
            self.assertEqual(hashlib.sha256((self.out/name).read_bytes()).hexdigest(),sha,name)

    def test_conflicting_independent_dimension_chain_is_rejected(self):
        self.request['engineering']['modules']['dimensions']=json.loads((ROOT/'examples/issue50-dimensions.json').read_text())
        report=build_release(self.request,self.out)
        self.assertEqual(report['status'],'failed')
        self.assertIn('dimension_link',report['errors'])

    def test_conflicting_manufacturing_plan_is_rejected(self):
        self.request['platform']['assembly_plan']={'old_model':'unrelated'}
        report=build_release(self.request,self.out)
        self.assertEqual(report['status'],'failed')
        self.assertIn('manufacturing_link',report['errors'])

    def test_no_overwrite_or_input_mutation(self):
        before=copy.deepcopy(self.request)
        build_release(self.request,self.out)
        sentinel=self.out/'operator.txt';sentinel.write_text('preserve')
        with self.assertRaises(FileExistsError):build_release(self.request,self.out)
        self.assertEqual(sentinel.read_text(),'preserve');self.assertEqual(before,self.request)

    def test_existing_desktop_batch_executes_same_cli(self):
        report=execute_job({'kind':'unified','config':str(ROOT/'examples/unified-project.json'),'output_dir':str(self.out)},root=ROOT,runner=subprocess.run)
        self.assertEqual(report['status'],'review_required',report)
        self.assertEqual(report['returncode'],3)
        self.assertFalse(report['cad_verified'])
        self.assertEqual(report['events'][0]['stages']['engineering']['modules']['dimensions']['after_mm']['overall_length'],800)

    def test_failed_stage_does_not_hide_other_results(self):
        self.request['roller']['target_overall_mm']=1
        report=build_release(self.request,self.out)
        self.assertEqual(report['status'],'failed')
        self.assertIn('machine',report['stages']);self.assertIn('engineering',report['stages'])

    def test_bad_schema_refused_before_output(self):
        self.request['schema_version']=9
        with self.assertRaises(ValueError):build_release(self.request,self.out)
        self.assertFalse(self.out.exists())


class IntegratedFingerprintTests(unittest.TestCase):
    def test_compatibility_layer_changes_invalidate_sheet_plan(self):
        import sheet_metal_pipeline as pipeline
        original=pipeline.file_hash
        before=pipeline.code_hash()
        with patch.object(pipeline,'file_hash',side_effect=lambda p:'0'*64 if Path(p).as_posix().endswith('sw_compat/dispatch.py') else original(p)):
            self.assertNotEqual(before,pipeline.code_hash())

    def test_native_review_and_batch_bind_compatibility_code(self):
        from ql5050px.production_review import code_fingerprint
        from ql5050px.modeling_supervisor import supervise
        code=code_fingerprint()
        self.assertIn('sw_compat/dispatch.py',code)
        self.assertIn('owned_document_lifetime.py',code)
        with tempfile.TemporaryDirectory() as tmp:
            supervise([{'id':'fingerprint'}],Path(tmp)/'batch',stop_requested=lambda:True)
            manifest=json.loads((Path(tmp)/'batch/source-manifest.json').read_text())
            self.assertIn('sw_compat/dispatch.py',manifest['code_sha256'])
            self.assertTrue(all('\\' not in p for p in manifest['code_sha256']))
