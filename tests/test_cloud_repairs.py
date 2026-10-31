"""Portable regression checks; no CAD executable or COM object is used."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import dwg_converter
import sw_session
from batch_export import SheetPartResult


class CloudRepairTests(unittest.TestCase):
    def test_degraded_and_existing_artifacts_do_not_mean_acceptance(self):
        self.assertEqual(SheetPartResult(None, True, auto_bend_abandoned=True).status, 'degraded')
        self.assertEqual(SheetPartResult(None, True, skipped=True).status, 'unverified_existing')
        self.assertEqual(SheetPartResult(None, False).status, 'failed')

    def test_fabricated_exclusive_lease_cannot_write_outside_worker(self):
        lease = sw_session.SessionLease('fake', verified_exclusive=True, spawned_pid=123)
        lease.bind_com_thread(threading.get_ident())
        with self.assertRaises(sw_session.SessionOwnershipError):
            sw_session.require_model_write(lease)

    def test_native_pid_kill_is_disabled_without_lifetime_handle(self):
        lease = sw_session.SessionLease('fake', verified_exclusive=True, spawned_pid=123)
        lease.probe = lambda pid: None
        with patch.object(lease, 'prove_exclusive', return_value=True), patch.object(sw_session.os, 'kill') as kill:
            with self.assertRaises(sw_session.SessionOwnershipError):
                sw_session.terminate_owned_process(lease)
            kill.assert_not_called()

    def test_converter_failure_does_not_accept_partial_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.dwg'
            target = Path(folder) / 'output.dxf'
            source.write_bytes(b'synthetic')
            def failed(*args, **kwargs):
                self.assertEqual(kwargs['timeout'], 120)
                target.write_bytes(b'partial')
                return subprocess.CompletedProcess(args, 1, '', 'failed')
            with patch.object(dwg_converter, '_dwg2dxf_candidates', return_value=[Path('fake')]), patch.object(dwg_converter.subprocess, 'run', side_effect=failed):
                with self.assertRaises(dwg_converter.DwgConversionError):
                    dwg_converter.convert_dwg_with_libredwg(source, target)

    def test_converter_timeout_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.dwg'
            source.write_bytes(b'synthetic')
            with patch.object(dwg_converter, '_dwg2dxf_candidates', return_value=[Path('fake')]), patch.object(dwg_converter.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fake', 120)):
                with self.assertRaises(dwg_converter.DwgConversionError):
                    dwg_converter.convert_dwg_with_libredwg(source, Path(folder) / 'output.dxf')
