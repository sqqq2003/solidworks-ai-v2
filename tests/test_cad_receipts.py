"""Real SQLite contention/crash receipts, with fake CAD/process evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cad_checkpoint import create_checkpoint, digest_file
from cad_receipts import (IdempotencyConflict, ReceiptStore, ReconcileRequired,
                          UNRESOLVED, assert_no_unresolved, request_identity)
from cad_reconcile import verify_quiescent_baseline


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.store = ReceiptStore(self.root / 'receipts.sqlite3')
        self.source = self.root / 'user.SLDPRT'; self.source.write_bytes(b'fixture original')
        self.payload = {'length_mm': 800}

    def begin(self, **kw):
        return self.store.begin(self.source, 'revision-1', self.payload, **kw)

    def test_completed_response_is_cached_without_admitting_new_writer(self):
        row = self.begin(); result = {'status': 'review_required', 'marker': 'fixture'}
        self.store.finish(row['key'], row['owner'], result, succeeded=True)
        replay = self.begin()
        self.assertTrue(replay['replayed']); self.assertEqual(replay['status'], 'COMPLETED')
        self.assertEqual(replay['result'], result)

    def test_failed_response_is_not_implicitly_retried(self):
        row = self.begin(); self.store.finish(row['key'], row['owner'], {'status': 'failed'}, succeeded=False)
        self.assertTrue(self.begin()['replayed']); self.assertEqual(self.begin()['status'], 'FAILED')

    def test_same_explicit_key_different_payload_or_revision_is_conflict(self):
        self.begin(key='client-request-1')
        with self.assertRaisesRegex(IdempotencyConflict, 'IDEMPOTENCY_CONFLICT'):
            self.store.begin(self.source, 'revision-1', {'length_mm': 900}, key='client-request-1')
        with self.assertRaises(IdempotencyConflict):
            self.store.begin(self.source, 'revision-2', self.payload, key='client-request-1')

    def test_automatic_key_is_canonical_and_binds_document_revision_payload(self):
        a = request_identity(self.source, 'r1', {'b': 2, 'a': 1})
        self.assertEqual(a, request_identity(self.source, 'r1', {'a': 1, 'b': 2}))
        self.assertNotEqual(a['key'], request_identity(self.source, 'r2', {'a': 1, 'b': 2})['key'])

    def test_running_and_every_uncertain_state_block_new_requests(self):
        row = self.begin()
        for state in UNRESOLVED:
            if state not in {'RUNNING', 'RECOVERING'}:
                self.store.quarantine(row['key'], row['owner'], state)
            with self.assertRaises(ReconcileRequired):
                self.store.begin(self.source, 'another revision', self.payload)
            with self.assertRaises(ReconcileRequired): self.begin()

    def test_late_return_cannot_clear_timeout_and_rollback_unknown_dominates(self):
        row = self.begin()
        self.store.quarantine(row['key'], row['owner'], 'OUTCOME_UNKNOWN')
        self.store.returned(row['key'], row['owner'])
        self.assertEqual(self.store.get(row['key'])['session_state'], 'RETURNED_LATE')
        with self.assertRaises(ReconcileRequired):
            self.store.finish(row['key'], row['owner'], {}, succeeded=True)
        self.store.quarantine(row['key'], row['owner'], 'ROLLBACK_UNCONFIRMED')
        self.store.returned(row['key'], row['owner'])
        self.assertEqual(self.store.get(row['key'])['session_state'], 'ROLLBACK_UNCONFIRMED')

    def test_wrong_owner_and_quarantined_owner_cannot_write(self):
        row = self.begin(); self.store.assert_writer(row['key'], row['owner'])
        with self.assertRaises(ReconcileRequired): self.store.assert_writer(row['key'], 'other-owner')
        self.store.quarantine(row['key'], row['owner'], 'OUTCOME_UNKNOWN')
        with self.assertRaises(ReconcileRequired): self.store.assert_writer(row['key'], row['owner'])

    def test_rejected_reconcile_leaves_persistent_recovering_and_original_result(self):
        row = self.begin()
        def reject(receipt): raise ReconcileRequired('old process alive')
        with self.assertRaises(ReconcileRequired): self.store.reconcile(row['key'], reject)
        self.assertEqual(ReceiptStore(self.store.path).get(row['key'])['session_state'], 'RECOVERING')
        with self.assertRaises(ReconcileRequired): self.begin()

    def test_legacy_owned_entry_is_blocked_by_shared_unresolved_receipt(self):
        self.begin()
        with patch('cad_receipts.default_database', return_value=self.store.path):
            with self.assertRaises(ReconcileRequired): assert_no_unresolved()

    def test_process_crash_after_admission_is_still_running_after_restart(self):
        code = '''from cad_receipts import ReceiptStore
import os,sys
ReceiptStore(sys.argv[1]).begin(sys.argv[2], 'crash-revision', {'fixture':True})
os._exit(23)
'''
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        result = subprocess.run([sys.executable, '-c', code, str(self.store.path), str(self.source)], env=env)
        self.assertEqual(result.returncode, 23)
        self.assertEqual(ReceiptStore(self.store.path).unresolved()[0]['session_state'], 'RUNNING')
        with self.assertRaises(ReconcileRequired): self.begin()

    def test_two_independent_processes_admit_exactly_one_writer(self):
        code = '''from cad_receipts import ReceiptStore,ReconcileRequired
import sys
try:
    ReceiptStore(sys.argv[1]).begin(sys.argv[2], sys.argv[3], {'fixture':True})
    print('admitted')
except ReconcileRequired:
    print('blocked')
'''
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        children = [subprocess.Popen([sys.executable, '-c', code, str(self.store.path), str(self.source), str(i)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env) for i in range(2)]
        results = [child.communicate(timeout=10) for child in children]
        self.assertEqual([child.returncode for child in children], [0, 0], results)
        self.assertEqual(sorted(out.strip() for out, err in results), ['admitted', 'blocked'])

    def baseline(self):
        scope = self.root / 'isolated'; scope.mkdir()
        target = scope / 'copy.SLDPRT'; target.write_bytes(b'baseline')
        original = {str(self.source): digest_file(self.source)}
        cp = create_checkpoint([target], self.root / 'checkpoint', scope=scope,
                               snapshot={'features': ['Boss1'], 'bodies': [{'count': 1}]}, originals=original)
        metadata = {'controller': {'pid': 123, 'creation_filetime': 10},
                    'process': {'pid': 456, 'creation_filetime': 20}, 'original_sha256': original,
                    'checkpoint': {'directory': str(cp.directory), 'manifest_sha256': cp.manifest_sha256, 'scope': str(cp.scope)}}
        return self.begin(metadata=metadata), target

    def test_quiescent_byte_verified_reconcile_records_failed_without_replaying(self):
        row, target = self.baseline()
        result = self.store.reconcile(row['key'], lambda r: verify_quiescent_baseline(r, process_probe=lambda identity: False))
        self.assertEqual(result['status'], 'FAILED'); self.assertEqual(result['session_state'], 'RESOLVED')
        self.assertFalse(result['result']['proof']['native_reopen_verified'])
        self.assertTrue(self.begin()['replayed'])
        self.assertFalse(result['result']['manufacturing_approved'])

    def test_alive_process_changed_target_and_changed_source_each_refuse_reconcile(self):
        row, target = self.baseline()
        with self.assertRaisesRegex(ReconcileRequired, 'still alive'):
            verify_quiescent_baseline(row, process_probe=lambda identity: True)
        target.write_bytes(b'partially changed')
        with self.assertRaisesRegex(ReconcileRequired, 'not restored'):
            verify_quiescent_baseline(row, process_probe=lambda identity: False)
        target.write_bytes(b'baseline'); self.source.write_bytes(b'changed')
        with self.assertRaisesRegex(ReconcileRequired, 'original source changed'):
            verify_quiescent_baseline(row, process_probe=lambda identity: False)

    def test_unsealed_crash_is_not_released_even_after_processes_exit(self):
        row = self.begin(metadata={'controller': {'pid': 1, 'creation_filetime': 2},
                                   'process': {'pid': 3, 'creation_filetime': 4},
                                   'original_sha256': {str(self.source): digest_file(self.source)}})
        with self.assertRaisesRegex(ReconcileRequired, 'not sealed'):
            verify_quiescent_baseline(row, process_probe=lambda identity: False)


if __name__ == '__main__': unittest.main()
