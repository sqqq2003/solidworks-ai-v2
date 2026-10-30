"""Actual file rollback with fake CAD snapshots; never SolidWorks evidence."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from cad_checkpoint import (create_checkpoint, digest_file, inspect_checkpoint,
                            remove_checkpoint, restore_checkpoint)
from roller_variant.execution import execute_variant
from test_roller_variant import fixture


class ByteDriver:
    """Inject failure after a real isolated file has already changed."""
    simulated = False  # Exercises the native-contract gate with a fake backend.

    def __init__(self, request, fail=True, foreign=False, reopen_bad=False):
        self.request = request; self.fail = fail; self.foreign = foreign
        self.reopen_bad = reopen_bad; self.writes = 0; self.events = []

    def isolate(self, request, folder):
        folder.mkdir()
        self.root = folder.parent; self.path = folder / 'roller.SLDPRT'
        self.path.write_text(json.dumps({k: v['value'] for k, v in request['measurements'].items()}))
        self.initial = self.path.read_bytes()

    def read_all(self):
        return json.loads(self.path.read_bytes())

    def feature_inventory(self):
        return ['Sketch1', 'Boss1']

    def mechanical_inventory(self):
        return {'scope': 'fake_no_mates'}

    def reopen_snapshot(self):
        self.events.append('reopen')
        return {'features': self.feature_inventory(),
                'bodies': [{'count': 2 if self.reopen_bad and self.writes else 1}],
                'dimensions': self.read_all()}

    def assert_closed(self, targets):
        self.events.append('closed_checked')
        if self.foreign:
            raise RuntimeError('foreign ActiveDoc; restore refused')

    def close_for_restore(self, targets):
        self.events.append('close_owned')
        self.assert_closed(targets)

    def checkpoint(self):
        self.saved = create_checkpoint([self.path], self.root / 'rollback-checkpoint',
                                      scope=self.path.parent, snapshot=self.reopen_snapshot())
        return self.saved

    def restore(self, checkpoint):
        return restore_checkpoint(checkpoint, self)

    def write(self, change):
        values = self.read_all(); values[change['parameter']] = change['after_mm']
        self.path.write_text(json.dumps(values)); self.writes += 1
        if self.fail:
            raise RuntimeError('injected failure after first file write')

    def rebuild_save(self):
        values = self.read_all()
        values['overall_length'] = values['barrel_length'] + values['left_projection'] + values['right_projection']
        self.path.write_text(json.dumps(values))

    def reopen(self): pass
    def axial_extent(self, axis): return self.read_all()['overall_length']
    def close(self): pass


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.scope = self.root / 'isolated'; self.scope.mkdir()
        self.target = self.scope / 'part.SLDPRT'; self.target.write_bytes(b'original fixture bytes')
        self.source = self.root / 'user.SLDPRT'; self.source.write_bytes(b'user bytes remain untouched')

    def checkpoint(self):
        return create_checkpoint([self.target], self.root / 'checkpoint', scope=self.scope,
                                 snapshot={'features': ['Boss1'], 'bodies': [{'count': 1}]},
                                 originals={str(self.source): digest_file(self.source)})

    def adapter(self, *, mismatch=False, foreign=False):
        test = self
        class Adapter:
            def close_for_restore(self, paths):
                if foreign: raise RuntimeError('foreign ActiveDoc')
            def assert_closed(self, paths): pass
            def reopen_snapshot(self):
                test.assertEqual(test.target.read_bytes(), b'original fixture bytes')
                return {'features': ['Boss1'], 'bodies': [{'count': 2 if mismatch else 1}]}
        return Adapter()

    def test_half_modified_file_restored_and_reopened_with_same_hash(self):
        cp = self.checkpoint(); before = digest_file(self.target)
        self.target.write_bytes(b'half edited native file fixture')
        result = restore_checkpoint(cp, self.adapter())
        self.assertEqual(result['state'], 'RESTORED'); self.assertEqual(digest_file(self.target), before)
        self.assertTrue(result['reopen_snapshot_verified']); self.assertEqual(self.source.read_bytes(), b'user bytes remain untouched')

    def test_failure_in_actual_roller_execution_rolls_back_real_file_bytes(self):
        driver = ByteDriver(fixture())
        report = execute_variant(fixture(), driver, self.root / 'run')
        self.assertEqual(report['status'], 'failed'); self.assertEqual(driver.writes, 1)
        self.assertEqual(driver.path.read_bytes(), driver.initial)
        self.assertEqual(report['rollback']['state'], 'RESTORED')

    def test_rollover_failure_stays_unconfirmed_when_snapshot_differs(self):
        driver = ByteDriver(fixture(), reopen_bad=True)
        report = execute_variant(fixture(), driver, self.root / 'run')
        self.assertEqual(report['rollback']['state'], 'ROLLBACK_UNCONFIRMED')
        self.assertFalse((driver.saved.directory / 'rollback.json').exists())

    def test_foreign_active_document_never_allows_byte_replace(self):
        cp = self.checkpoint(); self.target.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'foreign'):
            restore_checkpoint(cp, self.adapter(foreign=True))
        self.assertEqual(self.target.read_bytes(), b'changed')

    def test_modified_backup_or_manifest_rejected_before_restore(self):
        cp = self.checkpoint(); manifest = inspect_checkpoint(cp)
        backup = cp.directory / manifest['files'][0]['backup']; backup.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'backup changed'): restore_checkpoint(cp, self.adapter())
        self.assertEqual(self.target.read_bytes(), b'original fixture bytes')

    def test_manifest_tamper_cannot_redirect_restore(self):
        cp = self.checkpoint(); path = cp.directory / 'manifest.json'
        manifest = json.loads(path.read_bytes()); manifest['files'][0]['target'] = str(self.source)
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'manifest changed'): restore_checkpoint(cp, self.adapter())
        self.assertEqual(self.source.read_bytes(), b'user bytes remain untouched')

    def test_no_cleanup_without_own_manifest_and_no_directory_sweep(self):
        cp = self.checkpoint(); user = cp.directory / 'extra.SLDPRT'; user.write_bytes(b'user')
        with self.assertRaisesRegex(ValueError, 'nothing deleted'): remove_checkpoint(cp)
        self.assertTrue((cp.directory / 'manifest.json').exists()); self.assertEqual(user.read_bytes(), b'user')
        user.unlink(); remove_checkpoint(cp)
        self.assertFalse(cp.directory.exists()); self.assertTrue(self.target.exists()); self.assertTrue(self.source.exists())

    def test_symlink_restore_alias_refused(self):
        alias = self.scope / 'alias.SLDPRT'
        try:
            alias.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation unavailable on this account; hardlink gate has a separate test')
        else:
            with self.assertRaises(ValueError):
                create_checkpoint([alias], self.root / 'checkpoint', scope=self.scope,
                                  snapshot={'features': [], 'bodies': []})
            alias.unlink()
    def test_hardlink_restore_alias_refused(self):
        alias = self.scope / 'alias.SLDPRT'
        alias.hardlink_to(self.target)
        with self.assertRaisesRegex(ValueError, 'alias'):
            create_checkpoint([self.target], self.root / 'checkpoint', scope=self.scope,
                              snapshot={'features': [], 'bodies': []})

    def test_multi_file_partial_replace_failure_keeps_manifest_for_reconcile(self):
        other = self.scope / 'second.SLDPRT'; other.write_bytes(b'second baseline')
        cp = create_checkpoint([self.target, other], self.root / 'checkpoint', scope=self.scope,
                               snapshot={'features': ['Boss1'], 'bodies': [{'count': 1}]})
        self.target.write_bytes(b'changed'); other.write_bytes(b'changed')
        import cad_checkpoint
        replace = cad_checkpoint.os.replace; calls = []
        def fail_second(source, target):
            calls.append(target)
            if len(calls) == 2: raise OSError('injected disk failure')
            return replace(source, target)
        with patch('cad_checkpoint.os.replace', side_effect=fail_second):
            with self.assertRaisesRegex(OSError, 'disk failure'): restore_checkpoint(cp, self.adapter())
        self.assertTrue((cp.directory / 'manifest.json').exists())
        self.assertFalse((cp.directory / 'rollback.json').exists())

    def test_original_user_file_change_refuses_restore(self):
        cp = self.checkpoint(); self.target.write_bytes(b'changed'); self.source.write_bytes(b'externally changed')
        with self.assertRaisesRegex(RuntimeError, 'original user CAD changed'): restore_checkpoint(cp, self.adapter())
        self.assertEqual(self.target.read_bytes(), b'changed')


if __name__ == '__main__': unittest.main()
