"""Formal launcher proof tests: fake processes and COM, real STA writer gate."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import sw_session
from sw_session import ProcessProbeInfo, SessionOwnershipError
from sw_owned_launch import bind_spawned
from solidworks_generator import _list_open_document_titles, _connect_task_solidworks


class Lifetime:
    pid = 43210
    executable = r'C:\Program Files\SOLIDWORKS\SLDWORKS.exe'
    def __init__(self):
        self.alive = True
    def probe(self, pid):
        return ProcessProbeInfo(self.pid, True, self.executable) if self.alive and pid == self.pid else None


class OwnedLaunchTests(unittest.TestCase):
    def test_rot_unknown_is_queried_for_dispatch_and_pid_is_still_required(self):
        from sw_owned_launch import _native_candidate
        unknown=MagicMock();dispatch=object();unknown.QueryInterface.return_value=dispatch
        moniker=MagicMock();moniker.GetDisplayName.return_value='SolidWorks_PID_43210'
        rot=MagicMock();rot.EnumRunning.return_value=[moniker];rot.GetObject.return_value=unknown
        pycom=MagicMock();pycom.GetRunningObjectTable.return_value=rot
        client=MagicMock();client.GetActiveObject.return_value=SimpleNamespace(GetProcessID=999)
        client.Dispatch.return_value=SimpleNamespace(GetProcessID=43210)
        with patch.dict(sys.modules,{'pythoncom':pycom,'win32com':SimpleNamespace(client=client),'win32com.client':client}):
            self.assertIs(_native_candidate(43210),client.Dispatch.return_value)
            unknown.QueryInterface.assert_called_once_with(pycom.IID_IDispatch)
            client.Dispatch.assert_called_once_with(dispatch)
            client.Dispatch.return_value=SimpleNamespace(GetProcessID=123)
            self.assertIsNone(_native_candidate(43210))

    def setUp(self):
        sw_session.reset_for_tests()
        self.addCleanup(sw_session.reset_for_tests)

    def on_sta(self, fn):
        return sw_session.run_on_task_sta(fn, timeout=5, task_name='fake-launch-contract')

    def test_success_uses_spawned_pid_and_never_refetches_active_object(self):
        lifetime = Lifetime()
        app = object()
        def job():
            binding = bind_spawned(lifetime, lambda pid:app, lambda a:lifetime.pid, lambda a:[],timeout=1)
            lease = sw_session.current_lease()
            self.assertTrue(lease.verified_exclusive)
            self.assertFalse(lease.attached_existing)
            sw_session.require_model_write()
            win32 = MagicMock()
            got, created = _connect_task_solidworks(lease, win32, MagicMock())
            self.assertIs(got, app)
            self.assertTrue(created)
            win32.client.GetActiveObject.assert_not_called()
            lifetime.alive = False
            with self.assertRaises(SessionOwnershipError):
                sw_session.require_model_write()
        self.on_sta(job)

    def test_wrong_active_pid_never_becomes_exclusive(self):
        def job():
            with self.assertRaises(SessionOwnershipError):
                bind_spawned(Lifetime(), lambda pid:object(), lambda a:999,lambda a:[],timeout=.01)
            self.assertFalse(sw_session.current_lease().verified_exclusive)
        self.on_sta(job)

    def test_forwarded_or_exited_process_refused(self):
        lifetime = Lifetime()
        lifetime.alive = False
        def job():
            with self.assertRaisesRegex(SessionOwnershipError,'exited'):
                bind_spawned(lifetime,lambda p:object(),lambda a:43210,lambda a:[],timeout=1)
        self.on_sta(job)

    def test_nonempty_or_unreadable_new_process_inventory_refused(self):
        for listing in (lambda app:['user-part'], lambda app:(_ for _ in ()).throw(RuntimeError('enumeration failed'))):
            with self.subTest(listing=listing):
                sw_session.reset_for_tests()
                def job():
                    with self.assertRaises((SessionOwnershipError,RuntimeError)):
                        bind_spawned(Lifetime(),lambda p:object(),lambda a:43210,listing,timeout=1)
                    self.assertFalse(sw_session.current_lease().verified_exclusive)
                self.on_sta(job)

    def test_unknown_document_appearing_later_blocks_writes(self):
        documents = []
        def job():
            bind_spawned(Lifetime(),lambda p:object(),lambda a:43210,lambda a:documents,timeout=1)
            lease = sw_session.current_lease()
            documents.append('task-part')
            lease.note_owned_document('task-part')
            sw_session.require_model_write()
            documents.append('foreign-part')
            with self.assertRaisesRegex(SessionOwnershipError,'unowned'):
                sw_session.require_model_write()
            self.assertTrue(lease.writes_blocked)
        self.on_sta(job)

    def test_inventory_property_binding_and_phantom_count(self):
        last = SimpleNamespace(GetTitle='part2',GetNext=None)
        first = SimpleNamespace(GetTitle=lambda:'part1',GetNext=lambda:last)
        app = SimpleNamespace(GetDocumentCount=2,GetFirstDocument=first)
        self.assertEqual(_list_open_document_titles(app),['part1','part2'])
        for count, head in ((33,None),(0,first),(1,first)):
            with self.assertRaises(SessionOwnershipError):
                _list_open_document_titles(SimpleNamespace(GetDocumentCount=lambda:count,GetFirstDocument=lambda:head))

    def test_keepalive_prevents_intermediate_exit(self):
        def job():
            app = MagicMock()
            bind_spawned(Lifetime(),lambda p:app,lambda a:43210,lambda a:[],timeout=1)
            lease = sw_session.current_lease()
            sw_session.release_task_documents(lease,app,title=None,close=False)
            app.ExitApp.assert_not_called()
        self.on_sta(job)

    def test_launcher_cannot_bind_off_worker(self):
        with self.assertRaises(SessionOwnershipError):
            bind_spawned(Lifetime(),lambda p:object(),lambda a:43210,lambda a:[],timeout=1)
