"""Issue #19 stage 2: checkpoints, crash-safe locks, orphan quarantine, teardown order.

Cloud-only tests; no live SolidWorks. Every Windows behavior asserted here
through fakes stays pending_windows_validation until Gork runs it on real
SolidWorks hardware.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src')]

from run_recovery import (RunLock, assert_release_order, quarantine_orphan_staging,
                          read_checkpoints, release_wrappers_in_order,
                          run_minimal_teardown, run_teardown_sequence,
                          validate_checkpoint_chain, write_checkpoint,
                          write_crash_package)


def _sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_chain_valid_then_tampered_product_falls_back(self):
        ckpt = self.root / 'ckpt'
        product = self.root / 'part.SLDPRT'
        product.write_bytes(b'part-bytes')
        write_checkpoint(ckpt, 'S0', plan_id='p1', code_sha256='c1')
        write_checkpoint(ckpt, 'S1', plan_id='p1', code_sha256='c1',
                         products=[{'name': 'part.SLDPRT', 'sha256': _sha(product)}],
                         evidence={'generation': {'auto_bent': True}})
        stage, ckpts = validate_checkpoint_chain(
            ckpt, plan_id='p1', code_sha256='c1', base_dir=self.root)
        self.assertEqual(stage, 'S1')
        self.assertEqual(ckpts['S1']['evidence']['generation']['auto_bent'], True)
        product.write_bytes(b'tampered')
        stage, _ckpts = validate_checkpoint_chain(
            ckpt, plan_id='p1', code_sha256='c1', base_dir=self.root)
        self.assertEqual(stage, 'S0')

    def test_chain_requires_contiguity_and_matching_fingerprint(self):
        ckpt = self.root / 'ckpt'
        write_checkpoint(ckpt, 'S1', plan_id='p1', code_sha256='c1')
        stage, _ckpts = validate_checkpoint_chain(
            ckpt, plan_id='p1', code_sha256='c1', base_dir=self.root)
        self.assertIsNone(stage)
        write_checkpoint(ckpt, 'S0', plan_id='p1', code_sha256='c1')
        stage, _ckpts = validate_checkpoint_chain(
            ckpt, plan_id='other', code_sha256='c1', base_dir=self.root)
        self.assertIsNone(stage)
        stage, _ckpts = validate_checkpoint_chain(
            ckpt, plan_id='p1', code_sha256='c2', base_dir=self.root)
        self.assertIsNone(stage)


class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _plant_lock(self, pid, heartbeat):
        lock_dir = self.root / '.label.lock'
        lock_dir.mkdir()
        (lock_dir / 'owner.json').write_text(json.dumps({
            'schema_version': 1, 'token': 'other', 'pid': pid,
            'plan_id': 'p1', 'started': heartbeat, 'heartbeat': heartbeat}))
        return lock_dir

    def test_live_owner_lock_is_never_stolen(self):
        self._plant_lock(os.getpid(), time.time())
        with self.assertRaises(RuntimeError):
            RunLock(self.root, 'label', plan_id='p1').acquire()
        self.assertTrue((self.root / '.label.lock').is_dir())

    def test_dead_pid_lock_is_archived_and_reacquired(self):
        proc = subprocess.Popen([sys.executable, '-c', 'pass'])
        proc.wait()
        dead_pid = proc.pid
        self._plant_lock(dead_pid, time.time())
        status = RunLock(self.root, 'label', plan_id='p1').acquire()
        self.assertEqual(status, 'recovered_stale_lock')
        archived = list(self.root.glob('.label.lock.archived-*'))
        self.assertEqual(len(archived), 1)
        self.assertTrue((self.root / '.label.lock' / 'owner.json').is_file())

    def test_expired_heartbeat_lock_is_refused_with_live_pid(self):
        self._plant_lock(os.getpid(), time.time() - 99999)
        with self.assertRaises(RuntimeError):
            RunLock(self.root,'label',plan_id='p1',stale_after_seconds=60).acquire()
        self.assertEqual(list(self.root.glob('.label.lock.archived-*')),[])

    def test_release_only_removes_own_lock(self):
        lock = RunLock(self.root, 'label', plan_id='p1')
        self.assertEqual(lock.acquire(), 'acquired')
        self.assertTrue(lock.heartbeat())
        self.assertTrue(lock.release())
        self.assertFalse(lock.release())
        self._plant_lock(os.getpid(), time.time())
        foreign = RunLock(self.root, 'label', plan_id='p1')
        foreign.acquired = True  # simulate a holder that never acquired
        with self.assertRaises(RuntimeError):
            foreign.release()


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_orphan_staging_quarantined_not_deleted(self):
        junk = self.root / '.label-aaa'
        junk.mkdir()
        (junk / 'part.trace.json').write_text('{}')
        good = self.root / '.label-bbb'
        (good / 'ckpt').mkdir(parents=True)
        (good / 'ckpt' / 'ckpt-S0.json').write_text('{}')
        resumable, quarantined = quarantine_orphan_staging(
            self.root, 'label',
            is_resumable=lambda d: (d / 'ckpt' / 'ckpt-S0.json').is_file())
        self.assertEqual(resumable, [good])
        self.assertEqual(len(quarantined), 1)
        self.assertFalse(junk.exists())
        self.assertTrue(quarantined[0].is_dir())
        self.assertTrue((quarantined[0] / 'part.trace.json').is_file())


class TeardownOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_release_before_uninitialize_ok_and_late_release_rejected(self):
        self.assertTrue(assert_release_order(
            ['release:model', 'release:feature', 'uninitialize']))
        with self.assertRaises(AssertionError):
            assert_release_order(['uninitialize', 'release:model'])

    def test_release_wrappers_runs_uninitialize_last_even_on_failure(self):
        events = []

        def _release(name):
            def _fn():
                events.append('release:' + name)
            return _fn

        def _failing():
            events.append('release:bad')
            raise RuntimeError('release exploded')

        report = release_wrappers_in_order(
            [('model', _release('model')), ('bad', _failing)],
            lambda: events.append('uninitialize'))
        self.assertFalse(report['ok'])
        self.assertEqual(report['failed'], ['bad'])
        self.assertLess(events.index('release:model'), events.index('uninitialize'))
        self.assertLess(events.index('release:bad'), events.index('uninitialize'))

    def test_teardown_sequence_records_all_five_steps_and_continues(self):
        calls = []

        def _boom():
            calls.append('exit_app')
            raise RuntimeError('ExitApp refused')

        report = run_teardown_sequence({
            'close_docs': lambda: calls.append('close') or ['a.SLDPRT'],
            'enumerate_titles': lambda: calls.append('enum') or [],
            'exit_app': _boom,
            'release': lambda: calls.append('release') or {'ok': True},
            'poll_exit_code': lambda: calls.append('poll') or 0,
        })
        self.assertEqual([s['step'] for s in report['steps']],
                         ['close_docs', 'enumerate_titles', 'exit_app', 'release',
                          'poll_exit_code'])
        self.assertEqual(report['exit_code'], 0)
        self.assertFalse(report['ok'])

    def test_minimal_teardown_with_fakes(self):
        calls = []

        def _fakes(exit_code):
            return {
                'spawn': lambda: calls.append('spawn') or 'pid-1',
                'close_docs': lambda: calls.append('close') or [],
                'enumerate_titles': lambda: calls.append('enum') or [],
                'exit_app': lambda: calls.append('exit') or None,
                'release': lambda: calls.append('release') or {'ok': True},
                'poll_exit_code': lambda: calls.append('poll') or exit_code,
            }

        ok = run_minimal_teardown(_fakes(0), repeat=2)
        self.assertTrue(ok['ok'])
        bad = run_minimal_teardown(_fakes(139), repeat=1)
        self.assertFalse(bad['ok'])
        self.assertTrue(bad['pending_windows_validation'])

    def test_crash_package_written(self):
        path = write_crash_package(
            self.root, plan_id='p1', error=RuntimeError('boom'),
            checkpoints={'S1': {'stage': 'S1'}},
            products=[{'name': 'part.SLDPRT', 'size': 12}])
        payload = json.loads(path.read_text())
        self.assertEqual(payload['plan_id'], 'p1')
        self.assertIn('boom', payload['error'])
        self.assertEqual(payload['last_checkpoints']['S1']['stage'], 'S1')


class RunPlanCheckpointTests(unittest.TestCase):
    """Mock-port integration: checkpoints land, resume skips generate, orphans move."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        import ezdxf
        from cad_analyzer import analyze_dxf
        from sheet_metal_pipeline import build_plan
        source = self.root / 'synthetic.dxf'
        doc = ezdxf.new('R2010')
        doc.units = ezdxf.units.MM
        space = doc.modelspace()
        space.add_lwpolyline([(0, 0), (100, 0), (100, 80), (0, 80)], close=True)
        space.add_circle((20, 20), 4)
        doc.layers.new('BEND', dxfattribs={'color': 1})
        space.add_line((50, 0), (50, 80), dxfattribs={'layer': 'BEND', 'color': 1})
        doc.saveas(source)
        analysis = analyze_dxf(source)
        outer = max(range(len(analysis.profiles)),
                    key=lambda i: len(analysis.profiles[i].points)
                    if analysis.profiles[i].kind != 'CIRCLE' else 0)
        self.analysis = analysis
        self.plan = build_plan(analysis, profile_index=outer, thickness_mm=2.5,
                               radius_mm=1, angle_degrees=90, k_factor=.4,
                               flip_direction=False, bends_confirmed=True)

    def test_checkpoints_land_and_resume_skips_generate(self):
        from sheet_metal_pipeline import MockSheetMetalPort, run_plan
        out1 = self.root / 'out1'
        first = run_plan(self.analysis, self.plan, out1, MockSheetMetalPort())
        self.assertEqual(first['status'], 'simulated_pass')
        dest1 = Path(first['output_dir'])
        # Checkpoint evidence lives in a hidden sibling dir so the published
        # artifact dir stays result + products only.
        ckpt1 = out1 / ('.simulation-' + self.plan['plan_id'] + '.ckpt')
        for stage in ('S0', 'S1', 'S2', 'S3', 'S4', 'S5'):
            self.assertTrue((ckpt1 / ('ckpt-' + stage + '.json')).is_file(),
                            'missing checkpoint ' + stage)

        class CountingPort(MockSheetMetalPort):
            def __init__(self):
                self.generate_calls = 0

            def generate(self, analysis, plan, part):
                self.generate_calls += 1
                raise AssertionError('generate must be skipped on checkpoint resume')

        out2 = self.root / 'out2'
        label = 'simulation-' + self.plan['plan_id']
        stage = out2 / ('.' + label + '-crashsim')
        (stage / 'ckpt').mkdir(parents=True)
        (stage / 'part.trace.json').write_bytes((dest1 / 'part.trace.json').read_bytes())
        for name in ('ckpt-S0.json', 'ckpt-S1.json'):
            (stage / 'ckpt' / name).write_bytes((ckpt1 / name).read_bytes())
        port = CountingPort()
        resumed = run_plan(self.analysis, self.plan, out2, port)
        self.assertEqual(resumed['status'], 'simulated_pass')
        self.assertTrue(resumed['resumed'])
        self.assertEqual(port.generate_calls, 0)

    def test_orphan_staging_quarantined_on_next_run(self):
        from sheet_metal_pipeline import MockSheetMetalPort, run_plan
        out = self.root / 'out3'
        label = 'simulation-' + self.plan['plan_id']
        junk = out / ('.' + label + '-junk')
        junk.mkdir(parents=True)
        (junk / 'part.trace.json').write_text('{}')
        result = run_plan(self.analysis, self.plan, out, MockSheetMetalPort())
        self.assertEqual(result['status'], 'simulated_pass')
        self.assertFalse(junk.exists())
        orphaned = list((out / 'orphaned').iterdir())
        self.assertEqual(len(orphaned), 1)
        self.assertTrue((orphaned[0] / 'part.trace.json').is_file())


if __name__ == '__main__':
    unittest.main()

