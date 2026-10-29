"""Native entry integration with fake COM/driver/process probes only."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import sw_session
from cad_receipts import ReceiptStore, ReconcileRequired
from roller_variant.native import RollerDriver, run_native
from test_cad_checkpoint import ByteDriver
from test_roller_variant import fixture
from test_sw_session_safety import _make_exclusive, FakeApp


class NativeRecoveryContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root / 'user.SLDPRT'
        self.request = fixture(); self.source.write_bytes(b'synthetic source; never native evidence')
        self.request['source_document'] = str(self.source)
        for row in self.request['mappings']['parameters']: row['document'] = str(self.source)
        self.db = self.root / 'receipts.sqlite3'; self.lease = SimpleNamespace()
        self.drivers = []; self.fail = False; self.reopen_bad = False
        def driver(lease, root):
            result = ByteDriver(self.request, fail=self.fail, reopen_bad=self.reopen_bad)
            self.drivers.append(result); return result
        mocks = [patch('roller_variant.native.sys.platform', 'win32'),
                 patch('sw_session.current_lease', return_value=self.lease),
                 patch('sw_session.run_on_task_sta', side_effect=lambda fn, **kwargs: fn()),
                 patch('sw_owned_launch.owned_solidworks', side_effect=lambda path: nullcontext()),
                 patch('cad_reconcile.current_controller_identity', return_value={'pid': 101, 'creation_filetime': 1}),
                 patch('cad_reconcile.owned_process_identity', return_value={'pid': 202, 'creation_filetime': 2}),
                 patch('roller_variant.native.RollerDriver', side_effect=driver)]
        for mock in mocks: mock.start(); self.addCleanup(mock.stop)

    def call(self, folder='run', **options):
        return run_native(self.request, self.root / folder, self.root / 'SLDWORKS.exe', state_db=self.db, **options)

    def test_entry_writes_once_and_duplicate_returns_receipt_without_new_directory(self):
        report = self.call(); self.assertEqual(report['status'], 'saved_reopened_readback')
        self.assertEqual(report['request_receipt']['status'], 'COMPLETED')
        replay = self.call('different-out')
        self.assertTrue(replay['request_receipt']['replayed']); self.assertEqual(len(self.drivers), 1)
        self.assertFalse((self.root / 'different-out').exists())
        self.assertEqual(self.source.read_bytes(), b'synthetic source; never native evidence')

    def test_mid_write_rollback_records_failed_and_same_key_is_never_retried(self):
        self.fail = True; report = self.call()
        self.assertEqual(report['rollback']['state'], 'RESTORED')
        self.assertEqual(report['request_receipt']['status'], 'FAILED')
        self.assertEqual(report['request_receipt']['session_state'], 'RESOLVED')
        self.assertTrue(self.call('other')['request_receipt']['replayed'])
        self.assertEqual(self.drivers[0].path.read_bytes(), self.drivers[0].initial)
        self.assertEqual(len(self.drivers), 1)

    def test_unconfirmed_rollback_quarantines_all_later_native_attempts(self):
        self.fail = True; self.reopen_bad = True; report = self.call()
        self.assertEqual(report['request_receipt']['session_state'], 'ROLLBACK_UNCONFIRMED')
        with self.assertRaises(ReconcileRequired): self.call('other')
        self.request['target_overall_mm'] = 750
        with self.assertRaises(ReconcileRequired): self.call('other-request')
        self.assertEqual(len(self.drivers), 1)

    def test_timeout_leaves_unknown_and_does_not_replay(self):
        with patch('sw_session.run_on_task_sta', side_effect=sw_session.SwCallTimeoutError('fake timeout')):
            with self.assertRaises(sw_session.SwCallTimeoutError): self.call()
        self.assertEqual(ReceiptStore(self.db).unresolved()[0]['session_state'], 'OUTCOME_UNKNOWN')
        with self.assertRaises(ReconcileRequired): self.call('other')
        self.assertEqual(self.drivers, [])

    def test_explicit_key_payload_conflict_is_checked_before_driver_creation(self):
        self.call(idempotency_key='external-1'); self.request['target_overall_mm'] = 750
        with self.assertRaisesRegex(ValueError, 'IDEMPOTENCY_CONFLICT'):
            self.call('other', idempotency_key='external-1')
        self.assertEqual(len(self.drivers), 1)


class NativeOwnershipContracts(unittest.TestCase):
    def test_different_active_document_is_never_closed_for_restore(self):
        with tempfile.TemporaryDirectory() as folder:
            driver = RollerDriver(SimpleNamespace(owned_docs={}), folder)
            class Model:
                def GetPathName(self): return str(Path(folder) / 'foreign.SLDPRT')
                def GetTitle(self): return 'foreign.SLDPRT'
            app = SimpleNamespace(ActiveDoc=Model())
            with patch.object(driver, 'guard', return_value=app), patch.object(driver, 'close_document') as close:
                with self.assertRaisesRegex(RuntimeError, 'exact owned restore target'):
                    driver.close_for_restore([str(Path(folder) / 'copy.SLDPRT')])
            close.assert_not_called()

    def test_close_doc_only_lease_forbids_even_explicit_termination_and_exit(self):
        lease = sw_session.SessionLease('fixture', close_doc_only=True)
        killed = []; app = FakeApp()
        with self.assertRaisesRegex(sw_session.SessionOwnershipError, 'CloseDoc-only'):
            sw_session.terminate_owned_process(lease, killer=killed.append)
        with self.assertRaisesRegex(sw_session.SessionOwnershipError, 'CloseDoc-only'):
            sw_session.exit_owned_application(lease, app)
        self.assertEqual(killed, []); self.assertEqual(app.calls, [])

    def test_live_writer_is_denied_immediately_after_durable_quarantine(self):
        sw_session.reset_for_tests(); self.addCleanup(sw_session.reset_for_tests)
        with tempfile.TemporaryDirectory() as folder:
            store = ReceiptStore(Path(folder) / 'receipts.sqlite3')
            row = store.begin(Path(folder) / 'fixture.SLDPRT', 'r1', {'fixture': True})
            def work():
                lease = sw_session.current_lease(); _make_exclusive(lease, 77)
                lease.durable_write_guard = lambda: store.assert_writer(row['key'], row['owner'])
                sw_session.require_model_write(lease)
                store.quarantine(row['key'], row['owner'], 'OUTCOME_UNKNOWN')
                with self.assertRaises(ReconcileRequired): sw_session.require_model_write(lease)
            sw_session.run_on_task_sta(work, timeout=2, durable_attempt=(store, row['key'], row['owner']))

    def test_close_doc_only_timeout_never_signals_even_a_proven_owned_pid(self):
        sw_session.reset_for_tests(); self.addCleanup(sw_session.reset_for_tests)
        release = threading.Event(); killed = []
        def work():
            lease = sw_session.current_lease(); _make_exclusive(lease, 77)
            lease.close_doc_only = True; lease.killer = killed.append
            release.wait(2)
        try:
            with self.assertRaises(sw_session.SwCallTimeoutError):
                sw_session.run_on_task_sta(work, timeout=0.05)
            self.assertEqual(killed, [])
            with self.assertRaises(sw_session.SessionOwnershipError):
                sw_session.run_on_task_sta(lambda: None, timeout=1)
        finally:
            release.set()
            worker = sw_session.active_worker()
            if worker:
                deadline = time.monotonic() + 2
                while worker.pending_lock_token is not None and time.monotonic() < deadline:
                    time.sleep(.01)


if __name__ == '__main__': unittest.main()
