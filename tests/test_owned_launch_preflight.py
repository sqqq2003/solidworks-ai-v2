"""Multiple-instance discovery tests: fake ROT/COM/processes only."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import sw_owned_launch as launch
import sw_session


class LaunchPreflight(unittest.TestCase):
    def setUp(self):
        sw_session.reset_for_tests()
        self.addCleanup(sw_session.reset_for_tests)
        self.user = MagicMock(name='existing_user_window')
        self.client = SimpleNamespace(GetActiveObject=MagicMock(return_value=self.user),
                                     Dispatch=MagicMock(side_effect=lambda obj: obj))

    def modules(self, entries):
        rot = SimpleNamespace(EnumRunning=lambda: list(entries),
                              GetObject=MagicMock(side_effect=lambda moniker: SimpleNamespace(QueryInterface=lambda iid:moniker.app)))
        com = SimpleNamespace(GetRunningObjectTable=lambda: rot,
                              CreateBindCtx=lambda flags: object(), IID_IDispatch=object(),
                              PumpWaitingMessages=lambda: None)
        modules = {'pythoncom': com, 'win32com': SimpleNamespace(client=self.client),
                   'win32com.client': self.client}
        return modules, rot

    def moniker(self, name, app):
        return SimpleNamespace(GetDisplayName=lambda *args: name, app=app)

    def test_exact_pid_rot_entry_is_selected_without_opening_user_object(self):
        own = SimpleNamespace(GetProcessID=lambda: 12345)
        entries = [self.moniker('SolidWorks_PID_999', self.user),
                   self.moniker('SolidWorks_PID_123450', self.user),
                   self.moniker('SolidWorks_PID_12345', own)]
        modules, rot = self.modules(entries)
        with patch.dict(sys.modules, modules):
            self.assertIs(launch._native_candidate(12345), own)
        rot.GetObject.assert_called_once_with(entries[-1])
        self.client.GetActiveObject.assert_not_called()
        self.client.Dispatch.assert_called_once_with(own)
        self.assertEqual(self.user.mock_calls, [])

    def test_no_target_returns_none_without_attaching_to_existing_instance(self):
        modules, rot = self.modules([self.moniker('SolidWorks_PID_999', self.user)])
        with patch.dict(sys.modules, modules):
            self.assertIsNone(launch._native_candidate(12345))
        rot.GetObject.assert_not_called()
        self.client.Dispatch.assert_not_called()
        self.client.GetActiveObject.assert_not_called()

    def test_matching_name_with_wrong_reported_pid_is_rejected(self):
        modules, _ = self.modules([self.moniker('SolidWorks_PID_12345',
                                  SimpleNamespace(GetProcessID=999))])
        with patch.dict(sys.modules, modules):
            self.assertIsNone(launch._native_candidate(12345))

    def test_unreadable_other_entry_does_not_hide_the_new_instance(self):
        bad = SimpleNamespace(GetDisplayName=MagicMock(side_effect=RuntimeError('unavailable')))
        own = SimpleNamespace(GetProcessID=12345)
        modules, _ = self.modules([bad, self.moniker('!SolidWorks_PID_12345', own)])
        with patch.dict(sys.modules, modules):
            self.assertIs(launch._native_candidate(12345), own)

    def test_existing_window_does_not_prevent_launch_and_own_binding(self):
        own = SimpleNamespace(GetProcessID=12345, GetDocumentCount=0, GetFirstDocument=None)
        modules, _ = self.modules([self.moniker('SolidWorks_PID_999', self.user),
                                  self.moniker('SolidWorks_PID_12345', own)])
        lifetime = SimpleNamespace(pid=12345, executable='SLDWORKS.exe',
            process=SimpleNamespace(poll=lambda:None),
            probe=lambda pid: sw_session.ProcessProbeInfo(12345, True, 'SLDWORKS.exe'))
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder)/'SLDWORKS.exe'
            exe.touch()
            def job():
                # Keep the real Linux writer lock; fake Windows only inside STA.
                with patch.object(launch.sys, 'platform', 'win32'):
                    with launch.owned_solidworks(exe) as binding:
                        self.assertIs(binding.app, own)
                        sw_session.require_model_write()
                        self.assertEqual(binding.evidence()['instance_mode'], 'new_process_alongside_existing')
            with patch.dict(sys.modules, modules), \
                 patch.object(launch, 'WindowsProcessLifetime', return_value=lifetime) as spawn, \
                 patch('owned_document_lifetime.finish_owned_session'), \
                 patch('owned_document_lifetime.release_closed_session_references'):
                sw_session.run_on_task_sta(job, timeout=5, task_name='fake-coexistence')
                spawn.assert_called_once_with(exe)
        self.client.GetActiveObject.assert_not_called()
        self.assertEqual(self.user.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
