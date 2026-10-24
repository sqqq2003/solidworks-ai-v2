"""Focused offline lifecycle/evidence contracts; no SolidWorks execution."""
import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from ql5050px import modeling_supervisor as supervisor
from ql5050px.acceptance_report import collect_acceptance,export_acceptance,safe_source_name
from ql5050px.native_environment import inspect_environment

class RecoveryContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'batch'
    def process(self,cleanup='owned_document_closed',returncode=0):
        def launch(command,**kwargs):
            output=Path(command[-1]);output.mkdir()
            part=output/'part.SLDPRT';part.write_bytes(b'offline fixture, not CAD')
            (output/'checkpoint.json').write_text(json.dumps({'modeling':'saved_reopened','cleanup':cleanup,'output':str(part)}))
            class Process:
                pid=12345
                def wait(self,timeout=None):return returncode
            return Process()
        return launch
    def test_completed_resume_reuses_artifact(self):
        with patch.object(supervisor.subprocess,'Popen',side_effect=self.process()) as launch:
            first=supervisor.supervise([{'id':'a'},{'id':'b'}],self.root)
            supervisor.supervise([{'id':'a'},{'id':'b'}],self.root,resume=True)
            self.assertEqual(launch.call_count,2)
        self.assertEqual(first['counts'],{'completed':2})
        self.assertTrue((self.root/'source-manifest.json').is_file())
        self.assertFalse((self.root/'.supervisor.lock').exists())
    def test_unknown_cleanup_stops_and_blocks_retry(self):
        with patch.object(supervisor.subprocess,'Popen',side_effect=self.process('unknown')) as launch:
            result=supervisor.supervise([{'id':'a'},{'id':'b'},{'id':'c'}],self.root)
            self.assertEqual([r['status'] for r in result['results']],['needs_review','not_run','not_run'])
            with self.assertRaisesRegex(RuntimeError,'explicit recover-parts'):
                supervisor.supervise([{'id':'a'},{'id':'b'},{'id':'c'}],self.root,resume=True)
            self.assertEqual(launch.call_count,1)
    def test_safely_closed_failure_continues(self):
        with patch.object(supervisor.subprocess,'Popen',side_effect=self.process(returncode=1)) as launch:
            result=supervisor.supervise([{'id':'a'},{'id':'b'}],self.root)
            self.assertEqual(launch.call_count,2)
        self.assertEqual(result['counts'],{'needs_review':2})
    def test_existing_lock_refuses_spawn(self):
        self.root.mkdir();lock=self.root/'.supervisor.lock';lock.write_text('operator review required')
        with patch.object(supervisor.subprocess,'Popen') as launch:
            with self.assertRaises(FileExistsError):supervisor.supervise([{'id':'a'}],self.root,resume=True)
            launch.assert_not_called()
        self.assertTrue(lock.exists())
    def test_export_rehash_and_no_binary(self):
        with patch.object(supervisor.subprocess,'Popen',side_effect=self.process()):
            supervisor.supervise([{'id':'a'}],self.root)
        report=collect_acceptance(self.root)
        self.assertTrue(report['evidence_consistent']);self.assertFalse(report['manufacturing_approved'])
        out=Path(self.tmp.name)/'export';export_acceptance(self.root,out)
        with zipfile.ZipFile(out/'gork-acceptance.zip') as z:
            self.assertEqual(set(z.namelist()),{'acceptance.json','SHA256.json'})
            self.assertEqual(json.loads(z.read('SHA256.json'))['acceptance.json'],hashlib.sha256(z.read('acceptance.json')).hexdigest())
        part=next(self.root.rglob('*.SLDPRT'));part.write_bytes(b'changed')
        self.assertFalse(collect_acceptance(self.root)['evidence_consistent'])
    def test_external_artifact_and_source_paths_removed(self):
        self.root.mkdir();external=Path(self.tmp.name)/'outside.SLDPRT';external.write_bytes(b'private')
        (self.root/'source-manifest.json').write_text(json.dumps({'code_sha256':{'/secret': 'a'*64,'../secret':'b'*64,'ql5050px/a.py':'c'*64},'private':'secret'}))
        (self.root/'summary.json').write_text(json.dumps({'results':[{'id':'a','status':'completed','returncode':139,'artifacts':{'../outside.SLDPRT':'x'}}]}))
        report=collect_acceptance(self.root)
        self.assertFalse(report['evidence_consistent'])
        self.assertEqual(report['source_fingerprint']['code_sha256'],{'ql5050px/a.py':'c'*64})
        self.assertNotIn(str(external),json.dumps(report))
    def test_portable_source_paths_reject_both_os_roots(self):
        for name in ['/secret','//host/share/file',r'C:\secret',r'\secret',r'\\host\share\file',
                     'C:relative.py','../secret','ql/../../secret','ql\\secret','']:
            with self.subTest(name=name):self.assertFalse(safe_source_name(name))
        self.assertTrue(safe_source_name('ql5050px/acceptance_report.py'))
    def test_failed_and_not_run_batch_has_no_acceptance_green(self):
        self.root.mkdir()
        (self.root/'source-manifest.json').write_text(json.dumps({'code_sha256':{'ql5050px/a.py':'a'*64},'request_and_code_signature':'b'*64}))
        rows=[{'id':'plate','status':'needs_review','returncode':1,'modeling':'unknown','cleanup':'unknown','artifacts':{}}]
        rows.extend({'id':name,'status':'not_run'} for name in ['bracket','shaft','two_bend_sheet'])
        (self.root/'summary.json').write_text(json.dumps({'results':rows}))
        report=collect_acceptance(self.root)
        self.assertTrue(report['record_consistent'])
        self.assertFalse(report['execution_complete'])
        self.assertFalse(report['evidence_consistent'])
        self.assertEqual(report['counts'],{'needs_review':1,'not_run':3})
        self.assertTrue(all('job_not_completed' in row['evidence_errors'] for row in report['results']))
    def test_empty_evidence_cannot_pass(self):
        self.root.mkdir()
        (self.root/'summary.json').write_text(json.dumps({'results':[]}))
        report=collect_acceptance(self.root)
        self.assertFalse(report['evidence_consistent'])
        self.assertIn('missing_source_fingerprint',report['evidence_errors'])
    def test_nonwindows_diagnostic_does_not_spawn(self):
        with patch('sys.platform','linux'),patch.object(supervisor.subprocess,'Popen') as launch:
            report=inspect_environment()
            launch.assert_not_called()
        self.assertEqual(report['status'],'windows_required');self.assertFalse(report['cad_written'])

if __name__=='__main__':unittest.main()

