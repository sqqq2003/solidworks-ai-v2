import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from app_logging import WorkJournal


class WorkJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.journal=WorkJournal(self.root/'logs');self.addCleanup(self.journal.close)

    def test_structured_history_contains_failure_trace(self):
        self.journal.record('job_started',source='part.dxf',parameters={'length':800})
        try:raise ValueError('synthetic failure')
        except ValueError as error:self.journal.exception('job_failed',error)
        rows=self.journal.events();self.assertEqual(rows[-1]['level'],'ERROR')
        self.assertIn('ValueError',rows[-1]['details']['traceback'])
        self.assertIn('run_id',rows[-1]);self.assertIn('time',rows[-1])

    def test_common_credentials_are_redacted(self):
        self.journal.record('settings',config={'api_key':'do-not-export','password':'private'},note='sk-'+'a'*30)
        text='\n'.join(p.read_text(encoding='utf-8') for p in self.journal.folder.iterdir())
        self.assertNotIn('do-not-export',text);self.assertNotIn('private',text);self.assertNotIn('sk-'+'a'*30,text)

    def test_export_contains_only_journal_files_and_refuses_overwrite(self):
        (self.journal.folder/'customer.sldasm').write_bytes(b'CAD')
        (self.journal.folder/'customer.log.sldprt').write_bytes(b'CAD')
        path=self.root/'diagnostics.zip';self.journal.export(path)
        with zipfile.ZipFile(path) as archive:
            self.assertFalse(any(n.endswith(('.sldasm','.sldprt')) for n in archive.namelist()))
            self.assertTrue(any(n.endswith('.jsonl') for n in archive.namelist()))
        before=path.read_bytes()
        with self.assertRaises(FileExistsError):self.journal.export(path)
        self.assertEqual(before,path.read_bytes())

    def test_concurrent_threads_write_complete_json_lines(self):
        threads=[threading.Thread(target=lambda:self.journal.record('progress',step=1)) for _ in range(30)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(sum(r['event']=='progress' for r in self.journal.events()),30)

    def test_backend_result_has_correlated_start_and_finish(self):
        from project_workbench import execute_job
        source=self.root/'input.dxf';source.write_bytes(b'fixture')
        with patch('app_logging.get_journal',return_value=self.journal):
            result=execute_job({'kind':'sheet','action':'analyze','source':str(source)},runner=lambda *a,**kw:SimpleNamespace(returncode=0,stdout='{"event":"analysis"}',stderr=''))
        self.assertEqual(result['status'],'analyzed')
        rows=[r for r in self.journal.events() if r['event'] in ('job_started','job_finished')]
        self.assertEqual(rows[0]['details']['job_id'],rows[1]['details']['job_id'])
