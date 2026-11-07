"""Saved queue report history: read-only listing, honest about unreadable files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import report_history
from project_workbench import write_report


def sample_report(name, status='completed', artifact=None):
    row = {'name': name, 'kind': 'sheet', 'status': 'planned' if status == 'completed' else status}
    if artifact:
        row['artifact'] = {'path': artifact, 'sha256': '0' * 64}
    return {'schema_version': 1, 'status': status, 'counts': {row['status']: 1}, 'results': [row]}


class ReportHistoryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_lists_newest_first_and_ignores_side_files(self):
        old = write_report(sample_report('old.dxf'), self.folder)
        new = write_report(sample_report('new.dxf', 'review_required', artifact='C:/out/new.SLDPRT'), self.folder)
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_800_000_000, 1_800_000_000))
        (self.folder / 'notes.json').write_text('{}', encoding='utf-8')
        rows = report_history.list_reports(self.folder)
        self.assertEqual([row['path'] for row in rows], [str(new), str(old)])
        self.assertEqual(rows[0]['status'], 'review_required')
        self.assertEqual(rows[0]['names'], ['new.dxf'])
        self.assertEqual(rows[0]['artifacts'], ['C:/out/new.SLDPRT'])
        self.assertEqual(rows[1]['tasks'], 1)
        self.assertIsNone(rows[1]['error'])
        self.assertTrue(rows[0]['written_at'][:4].isdigit())

    def test_limit_and_validation(self):
        for index in range(3):
            write_report(sample_report(f'{index}.dxf'), self.folder)
        self.assertEqual(len(report_history.list_reports(self.folder, limit=2)), 2)
        for bad in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                report_history.list_reports(self.folder, limit=bad)

    def test_missing_folder_is_empty_history(self):
        self.assertEqual(report_history.list_reports(self.folder / 'none'), [])

    def test_unreadable_reports_are_listed_with_reason(self):
        broken = self.folder / ('project-report-' + 'a' * 32 + '.json')
        broken.write_text('{not json', encoding='utf-8')
        wrong = self.folder / ('project-report-' + 'b' * 32 + '.json')
        wrong.write_text(json.dumps({'results': 'nope'}), encoding='utf-8')
        rows = {Path(row['path']).name: row for row in report_history.list_reports(self.folder)}
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[broken.name]['error'])
        self.assertEqual(rows[wrong.name]['error'], '报告格式无效')
        self.assertIsNone(rows[wrong.name]['status'])

    def test_oversized_report_is_not_loaded(self):
        path = write_report(sample_report('big.dxf'), self.folder)
        with patch.object(report_history, 'MAX_REPORT_BYTES', 10):
            row = report_history.list_reports(self.folder)[0]
        self.assertEqual(row['path'], str(path))
        self.assertIn('16 MB', row['error'])

    def test_open_folder_only_targets_existing_directories(self):
        with self.assertRaises(FileNotFoundError):
            report_history.open_folder(self.folder / 'missing')
        with patch.object(report_history.sys, 'platform', 'linux'), \
             patch.object(report_history.subprocess, 'Popen') as popen:
            report_history.open_folder(self.folder)
        popen.assert_called_once_with(['xdg-open', str(self.folder)])


class HistoryCommandTests(unittest.TestCase):
    def test_project_history_command_is_read_only_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(sample_report('plate.dxf'), Path(tmp))
            before = sorted(Path(tmp).iterdir())
            done = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'work/project.py'), 'history',
                                   '--reports', tmp, '--limit', '5'], capture_output=True, text=True,
                                  encoding='utf-8', timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            payload = json.loads(done.stdout)
            self.assertEqual([row['path'] for row in payload['reports']], [str(path)])
            self.assertFalse(payload['cad_executed'])
            self.assertEqual(sorted(Path(tmp).iterdir()), before)
            bad = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'work/project.py'), 'history',
                                  '--reports', tmp, '--limit', '0'], capture_output=True, text=True,
                                 encoding='utf-8', timeout=60)
            self.assertEqual(bad.returncode, 1)


if __name__ == '__main__':
    unittest.main()
