"""Fake COM preflight only: no Windows/SolidWorks process is started."""
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sw_owned_launch as launch
from sw_session import SessionOwnershipError

class LaunchPreflight(unittest.TestCase):
    def test_active_registration_refuses_before_cad_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'SLDWORKS.exe';exe.touch()
            lease=SimpleNamespace(shared_com_bound=False,native_launch_attempt=None,writes_blocked=False,poisoned=False)
            with patch.object(launch.sys,'platform','win32'),patch.object(launch,'on_task_sta',return_value=True),patch.object(launch,'current_lease',return_value=lease),patch.object(launch,'_registered_application',return_value=object()),patch.object(launch,'WindowsProcessLifetime') as spawn,patch.dict(sys.modules,{'pythoncom':SimpleNamespace(),'solidworks_generator':SimpleNamespace(_list_open_document_titles=lambda app:[])}):
                with self.assertRaisesRegex(SessionOwnershipError,'no process spawned'):
                    with launch.owned_solidworks(exe):self.fail('unexpected yield')
                spawn.assert_not_called()
                self.assertIsNone(lease.native_launch_attempt)
    def test_empty_registration_is_only_preflight_not_ownership(self):
        self.assertIsNone(launch.refuse_registered_instance(lambda:None))
    def test_probe_error_cannot_be_treated_as_empty(self):
        def broken():raise RuntimeError('fixture probe failure')
        with self.assertRaisesRegex(RuntimeError,'fixture probe failure'):launch.refuse_registered_instance(broken)

if __name__=='__main__':unittest.main()
