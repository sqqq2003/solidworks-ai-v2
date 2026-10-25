import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from test_handoff_audit import audit_handoff


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'evidence.json').write_bytes(b'{}')
        self.matrix = {'schema_version': 1, 'lanes': [{'id': 'candidate', 'sha': 'a'*40,
                       'checks': [{'id': 'reopen', 'scope': 'native'}]}]}
        self.row = {'lane': 'candidate', 'id': 'reopen', 'sha': 'a'*40, 'status': 'passed',
                    'scope': 'native', 'environment': {'platform': 'Windows', 'solidworks_version': '2025 SP1.2'},
                    'process_exit_code': 0, 'artifacts': [{'path': 'evidence.json', 'sha256': hashlib.sha256(b'{}').hexdigest()}]}

    def audit(self, rows=None):
        return audit_handoff(self.matrix, {'schema_version': 1, 'results': [self.row] if rows is None else rows}, self.root)

    def test_coherent_is_not_native_approval(self):
        report = self.audit()
        self.assertEqual(report['status'], 'passed')
        self.assertFalse(report['manufacturing_approved'])
        self.assertEqual(report['native_acceptance'], 'requires_independent_review')

    def test_missing_and_duplicate(self):
        self.assertEqual(self.audit([])['status'], 'review_required')
        self.assertEqual(self.audit([self.row, self.row])['status'], 'review_required')

    def test_other_pin_not_accepted(self):
        self.row['sha'] = 'b'*40
        self.assertEqual(self.audit()['status'], 'review_required')

    def test_offline_cannot_fill_native_slot(self):
        self.row['scope'] = 'offline'
        self.row['environment'] = {}
        self.assertEqual(self.audit()['status'], 'review_required')

    def test_actual_nonzero_overrides_reported_pass(self):
        self.row['process_exit_code'] = 139
        self.assertEqual(self.audit()['status'], 'failed')

    def test_unknown_and_boolean_exit_not_zero(self):
        for value in (None, False, '0'):
            self.row['process_exit_code'] = value
            self.assertEqual(self.audit()['status'], 'review_required')

    def test_tamper(self):
        (self.root / 'evidence.json').write_bytes(b'changed')
        self.assertEqual(self.audit()['status'], 'failed')

    def test_escape_and_symlink(self):
        for name in ('../evidence.json', '/tmp/x', 'C:\\x', '..\\x'):
            self.row['artifacts'][0]['path'] = name
            self.assertEqual(self.audit()['status'], 'review_required')
        (self.root / 'link').symlink_to('/etc/hosts')
        self.row['artifacts'][0]['path'] = 'link'
        self.assertEqual(self.audit()['status'], 'review_required')

    def test_missing_artifact(self):
        self.row['artifacts'] = []
        self.assertEqual(self.audit()['status'], 'review_required')

    def test_failed_and_degraded_retained(self):
        for state in ('failed', 'degraded', 'review_required'):
            self.row['status'] = state
            self.assertEqual(self.audit()['status'], state)

    def test_unknown_row_not_ignored(self):
        other = copy.deepcopy(self.row)
        other['lane'] = 'wrong'
        self.assertEqual(self.audit([self.row, other])['status'], 'review_required')

    def test_duplicate_matrix_rejected(self):
        self.matrix['lanes'].append(self.matrix['lanes'][0])
        with self.assertRaises(ValueError):
            self.audit()
