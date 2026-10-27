"""Uploaded 2026-10-27 failure regression. Fake COM only, no native CAD."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
import dwg_converter
import sw_session
import sw_tool_cli
from project_workbench import build_command, execute_job, run_batch
from sw_owned_launch import bind_spawned


class FakeLifetime:
    pid = 54321
    executable = 'SLDWORKS.exe'

    def probe(self, pid):
        return sw_session.ProcessProbeInfo(pid, True, self.executable)


class Drawing:
    GetType = 3
    GetNext = None

    def __init__(self, app, target, *, rename=True, save_code=0):
        self.app, self.target = app, target
        self.title = 'Imported drawing'
        self.rename, self.save_code = rename, save_code

    def GetTitle(self):
        return self.title

    def SaveAs3(self, path, version, options):
        sw_session.require_model_write()  # import must already be registered
        if self.rename:
            self.title = self.target.name
        if not self.save_code:
            Path(path).write_bytes(b'fake DXF, not native evidence')
        return self.save_code


class FakeApp:
    UserControl = False

    def __init__(self, target, **options):
        self.documents, self.closed = [], []
        self.target, self.options = target, options
        self.import_calls = 0
        self.ExitApp = MagicMock()

    @property
    def GetDocumentCount(self):
        return len(self.documents)

    def GetFirstDocument(self):
        return self.documents[0] if self.documents else None

    @property
    def ActiveDoc(self):
        return self.GetFirstDocument()

    def GetImportFileData(self, path):
        return object()

    def LoadFile3(self, path, options, data):
        sw_session.require_model_write()
        self.import_calls += 1
        doc = Drawing(self, self.target, **self.options)
        self.documents.append(doc)
        return doc

    def CloseDoc(self, title):
        self.closed.append(title)
        self.documents[:] = [d for d in self.documents if d.title != title]


class DwgOwnedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'A-01左右牙条牙套.dwg'
        self.source.write_bytes(b'fake DWG')
        self.target = self.folder / 'converted.dxf'
        self.exe = self.folder / 'SLDWORKS.exe'
        self.exe.write_bytes(b'fake exe never executed')
        sw_session.reset_for_tests()
        self.addCleanup(sw_session.reset_for_tests)

    def on_sta(self, fn):
        return sw_session.run_on_task_sta(fn, timeout=5, task_name='fake-dwg')

    def convert(self, app):
        def job():
            bind_spawned(FakeLifetime(), lambda pid: app, lambda app: 54321,
                         lambda app: [d.title for d in app.documents], timeout=1)
            dwg_converter.convert_dwg_with_solidworks(self.source, self.target)
            sw_session.require_model_write()
            self.assertFalse(sw_session.current_lease().owned_docs)
        return self.on_sta(job)

    def test_owned_import_registers_before_save_and_tracks_saveas_rename(self):
        app = FakeApp(self.target)
        with patch('sw_session.connect_application') as attach:
            self.convert(app)
        attach.assert_not_called()
        self.assertEqual(app.closed, [self.target.name])
        self.assertTrue(self.target.is_file())
        app.ExitApp.assert_not_called()  # outer CLI owns lifetime
        self.assertEqual(self.source.read_bytes(), b'fake DWG')

    def test_property_title_and_method_type_bindings(self):
        app = FakeApp(self.target, rename=False)
        # Use another doc implementation to cover the inverse COM bindings.
        class PropertyDrawing(Drawing):
            GetTitle = property(lambda self: self.title)
            def GetType(self): return 3
        def property_load(*args):
            doc = PropertyDrawing(app, self.target, rename=False)
            app.documents.append(doc)
            return doc
        app.LoadFile3 = property_load
        self.convert(app)
        self.assertEqual(app.closed, ['Imported drawing'])

    def test_failed_import_and_wrong_document_type_clean_up_the_new_document(self):
        for failure in ('import', 'type'):
            sw_session.reset_for_tests()
            app = FakeApp(self.target)
            original = app.LoadFile3
            def load(*args):
                doc = original(*args)
                if failure == 'type':
                    doc.GetType = 1
                return None if failure == 'import' else doc
            app.LoadFile3 = load
            with self.assertRaises(dwg_converter.DwgConversionError):
                self.convert(app)
            self.assertEqual(app.closed, ['Imported drawing'])
            self.assertFalse(self.target.exists())

    def test_failed_save_closes_only_imported_document_under_new_title(self):
        app = FakeApp(self.target, save_code=16)
        with self.assertRaisesRegex(dwg_converter.DwgConversionError, '16'):
            self.convert(app)
        self.assertEqual(app.closed, [self.target.name])
        self.assertFalse(self.target.exists())
        app.ExitApp.assert_not_called()

    def test_unproved_session_returns_actionable_error_without_dispatch(self):
        with patch('sw_session.connect_application') as attach:
            with self.assertRaisesRegex(dwg_converter.DwgConversionError, '--sw-exe'):
                dwg_converter.convert_dwg_with_solidworks(self.source, self.target)
        attach.assert_not_called()

    def test_foreign_document_blocks_before_import_and_is_left_untouched(self):
        app = FakeApp(self.target)
        def job():
            bind_spawned(FakeLifetime(), lambda pid: app, lambda app: 54321,
                         lambda app: [d.title for d in app.documents], timeout=1)
            app.documents.append(SimpleNamespace(title='User document'))
            with self.assertRaises(sw_session.SessionOwnershipError):
                dwg_converter.convert_dwg_with_solidworks(self.source, self.target)
        self.on_sta(job)
        self.assertEqual(app.import_calls, 0)
        self.assertEqual(app.closed, [])
        app.ExitApp.assert_not_called()

    def test_converter_refuses_source_and_existing_target_before_com(self):
        self.target.write_bytes(b'keep')
        for target in (self.source, self.target):
            with self.assertRaises(dwg_converter.DwgConversionError):
                dwg_converter.convert_dwg_with_solidworks(self.source, target)
        self.assertEqual(self.target.read_bytes(), b'keep')

    def test_workbench_passes_selected_executable_for_dwg_analysis_and_plan(self):
        for action in ('analyze', 'plan'):
            job = dict(kind='turned', action=action, source=str(self.source), sw_exe=str(self.exe))
            cmd = build_command(job)
            self.assertEqual(cmd[cmd.index('--sw-exe') + 1], str(self.exe))
            self.assertNotIn('--out', cmd)
            self.assertNotIn('--verify-reopen', cmd)

    def test_dxf_analysis_stays_offline_and_dwg_without_path_keeps_libredwg_route(self):
        dxf = self.folder / 'input.dxf'
        dxf.write_text('fake')
        for source, exe in ((dxf, str(self.exe)), (self.source, '')):
            cmd = build_command(dict(kind='turned', source=str(source), sw_exe=exe))
            self.assertNotIn('--sw-exe', cmd)

    def test_dwg_analysis_uses_windows_gate_but_does_not_require_part_output(self):
        job = dict(kind='turned', action='analyze', source=str(self.source), sw_exe=str(self.exe))
        runner = MagicMock(return_value=SimpleNamespace(returncode=0, stderr='',
            stdout=json.dumps({'event': 'analysis', 'profiles': []})))
        with patch('project_workbench.sys.platform', 'win32'):
            result = execute_job(job, runner=runner)
        self.assertEqual(result['status'], 'analyzed')
        self.assertNotIn('artifact', result)
        with patch('project_workbench.sys.platform', 'linux'):
            self.assertEqual(execute_job(job, runner=runner)['status'], 'failed')

    def test_queue_stops_after_native_conversion_failure(self):
        job = dict(kind='turned', action='analyze', source=str(self.source), sw_exe=str(self.exe))
        execute = MagicMock(return_value={'status': 'failed'})
        result = run_batch([job, job], execute=execute)
        self.assertEqual(result['results'][1]['status'], 'not_run')
        self.assertEqual(execute.call_count, 1)

    def test_cli_dwg_analysis_and_plan_enter_owned_session_once_before_runner(self):
        calls = []
        binding = SimpleNamespace(evidence=lambda: {'mock_only': True})
        @contextmanager
        def owned(path):
            self.assertTrue(sw_session.on_task_sta())
            calls.append('enter')
            yield binding
            calls.append('exit')
        def run(args):
            self.assertEqual(calls[-1], 'enter')
            calls.append('analyze')
            return 0
        for flag in ('--analyze-only', '--plan-only'):
            calls.clear()
            with patch('sw_owned_launch.owned_solidworks', owned), patch('sw_tool_cli.run_turned', run), patch('sw_tool_cli.emit'):
                rc = sw_tool_cli.main(['--mode', 'turned', '--input', str(self.source),
                                      '--sw-exe', str(self.exe), flag])
            self.assertEqual(rc, 0)
            self.assertEqual(calls, ['enter', 'analyze', 'exit'])


if __name__ == '__main__':
    unittest.main()
