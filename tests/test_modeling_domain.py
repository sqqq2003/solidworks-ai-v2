"""Synthetic CAD ports with actual file rollback; no native SW acceptance."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from cad_checkpoint import create_checkpoint, digest_file, restore_checkpoint
from modeling_domain import analyze_draft, run_transaction, observe, body_clearance
from modeling_domain.contract import validate_plan, verify_bodies, digest
from modeling_domain.transaction import RevisionConflict

ROOT = Path(__file__).resolve().parents[1]


def example(name='block'):
    return json.loads((ROOT / 'examples' / ('modeling-' + name + '-v9.json')).read_text(encoding='utf-8'))


class BytePort:
    simulated = True

    def __init__(self, root):
        self.root = root
        self.scope = root / 'models'
        self.scope.mkdir()
        self.path = self.scope / 'work.SLDPRT'
        self.state = {'features': [{'name': 'Front Plane', 'native_type': 'RefPlane'}], 'bodies': []}
        self.writes = 0
        self.checkpoints = 0
        self.fail_after = None
        self.bad_body = False
        self.bad_reopen = False
        self.foreign = False
        self.quarantined = None
        self.camera = 'original'
        self.restore_camera_ok = True
        self.image_failure = False
        self.persist()
        self.initial = self.path.read_bytes()

    def persist(self):
        self.path.write_text(json.dumps(self.state, sort_keys=True), encoding='utf-8')

    def guard(self):
        if self.quarantined:
            raise RuntimeError('quarantined')

    def inventory(self):
        # Real SW can reverse native order and absorb a sketch as a subfeature.
        result = deepcopy(self.state)
        result['features'].reverse()
        return result

    def revision(self):
        return digest({'bytes': digest_file(self.path), 'state': self.state})

    def checkpoint(self):
        self.checkpoints += 1
        return create_checkpoint([self.path], self.root / 'checkpoint', scope=self.scope,
                                 snapshot=self.inventory())

    def create_feature(self, f):
        self.writes += 1
        self.state['features'].append({'name': f['id'], 'native_type': {
            'sketch': 'ProfileFeature', 'extrude': 'Boss', 'cut': 'Cut', 'revolve': 'Revolution'}[f['kind']]})
        if f['kind'] != 'sketch':
            self.state['bodies'] = [{'name': n, 'faces': 1 if self.bad_body else 6,
                'volume_mm3': 12000., 'bounds_mm': [0, 0, 0, 40, 30, 10]}
                for n in f['expected']['body_names']]
        self.persist()
        if self.fail_after == self.writes:
            raise RuntimeError('injected after a real write')

    def rebuild(self):
        pass

    def name_bodies(self, names):
        pass

    def save_reopen(self):
        self.state = json.loads(self.path.read_bytes())
        if self.bad_reopen:
            self.state['bodies'][0]['volume_mm3'] = 2

    def close_for_restore(self, targets):
        if self.foreign:
            raise RuntimeError('foreign ActiveDoc')

    def assert_closed(self, targets):
        pass

    def reopen_snapshot(self):
        self.state = json.loads(self.path.read_bytes())
        return self.inventory()

    def restore(self, cp):
        return restore_checkpoint(cp, self)

    def quarantine(self, state):
        self.quarantined = state

    def record(self, phase, data):
        pass

    def capture_camera(self):
        return self.camera

    def set_camera(self, name):
        self.camera = name

    def restore_camera(self, prior):
        if self.restore_camera_ok:
            self.camera = prior

    def camera_matches(self, prior):
        return self.camera == prior

    def capture_image(self, path):
        if self.image_failure:
            raise RuntimeError('image failed')
        path.write_bytes(b'BM synthetic camera image')

    def intersection_on_copies(self, left, right):
        return self.measurement


class ContractTests(unittest.TestCase):
    def test_examples_are_draft_only_and_never_native_evidence(self):
        for name in ('block', 'cut', 'revolve', 'two-bodies'):
            with self.subTest(name=name):
                plan = example(name)
                report = analyze_draft(plan)
                self.assertEqual(report['status'], 'draft_ready')
                self.assertEqual(report['plan_sha256'], digest(plan))
                self.assertFalse(report['native_executed'])
                self.assertFalse(report['estimated_geometry_is_acceptance'])
        self.assertEqual(analyze_draft(example())['estimates'][0]['estimated_volume_mm3'], 12000)

    def test_unsafe_unbounded_or_unconfirmed_plans_fail_before_port_use(self):
        base = example()
        variants = []
        for field, value in [('domain', 'sheet_metal'), ('contract_version', 2), ('pending_confirmation', True)]:
            p = deepcopy(base); p[field] = value; variants.append(p)
        for update in ({'merge': 1}, {'native_properties': {}}, {'depth_mm': -2}, {'script': 'x'}):
            p = deepcopy(base); p['features'][1]['parameters'].update(update); variants.append(p)
        p = deepcopy(base); p['features'] = p['features'][:1]; variants.append(p)
        p = deepcopy(base); del p['features'][1]['expected']['bounds_mm']; variants.append(p)
        p = deepcopy(base); p['features'][1]['expected']['max_volume_mm3'] = 1; variants.append(p)
        p = deepcopy(base); p['features'][0]['parameters']['entities'][0]['construction'] = 'yes'; variants.append(p)
        p = deepcopy(base); p['features'][1]['parameters']['sketch'] = 'AI_Boss'; variants.append(p)
        for p in variants:
            with self.subTest(p=p), self.assertRaises((ValueError, TypeError)):
                validate_plan(p)

    def test_revolve_requires_owned_construction_axis_and_keeps_later_dependencies(self):
        plan = example('revolve')
        extra = example()['features']
        extra[0]['id'] = 'AI_ExtraProfile'
        extra[0]['depends_on'] = ['AI_Revolve']
        extra[1]['id'] = 'AI_ExtraBoss'
        extra[1]['parameters']['sketch'] = 'AI_ExtraProfile'
        extra[1]['depends_on'] = ['AI_Revolve', 'AI_ExtraProfile']
        extra[1]['expected']['body_names'] = ['AI_Tube', 'AI_Main']
        plan['features'].extend(extra)
        self.assertEqual(validate_plan(plan), plan)
        for change in ('wrong_sketch', 'not_construction'):
            bad = example('revolve')
            if change == 'wrong_sketch':bad['features'][1]['parameters']['axis']['name'] = 'Line5@UserSketch'
            else:bad['features'][0]['parameters']['entities'][-1]['construction'] = False
            with self.assertRaises(ValueError):validate_plan(bad)

    def test_open_profile_blocks_native_admission(self):
        plan = example()
        plan['features'][0]['parameters']['entities'].pop()
        self.assertEqual(analyze_draft(plan)['status'], 'blocked')

    def test_revolve_axis_crossing_blocks_before_any_native_write(self):
        plan=example('revolve')
        for entity in plan['features'][0]['parameters']['entities'][:-1]:
            entity['start'][0]-=7
            entity['end'][0]-=7
        report=analyze_draft(plan)
        self.assertEqual(report['status'],'blocked')
        self.assertIn('revolve_profile_crosses_reviewed_axis',[r['reason'] for r in report['conflicts']])

    def test_nonempty_model_is_not_silently_adopted(self):
        report = analyze_draft(example(), inventory={'features': [], 'bodies': [{'name': 'user'}]})
        self.assertEqual(report['status'], 'blocked')

    def test_native_body_checks_reject_nan_wrong_names_bbox_and_face_count(self):
        expected = example()['features'][-1]['expected']
        good = {'name': 'AI_Main', 'faces': 6, 'volume_mm3': 12000., 'bounds_mm': [0, 0, 0, 40, 30, 10]}
        self.assertFalse(verify_bodies([good], expected)['engineering_accepted'])
        for update in ({'name': 'user'}, {'faces': 1}, {'volume_mm3': float('nan')},
                       {'volume_mm3': 12002}, {'bounds_mm': [0, 0, 0, 50, 30, 10]}):
            with self.subTest(update=update), self.assertRaises((ValueError, RuntimeError)):
                verify_bodies([{**good, **update}], expected)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.port = BytePort(self.root)

    def run_plan(self):
        plan = example()
        return run_transaction(plan, self.port, expected_revision=self.port.revision(),
                               reviewed_plan_sha256=digest(plan))

    def test_reverse_inventory_order_and_absorbed_sketch_can_complete_with_readback(self):
        result = self.run_plan()
        self.assertEqual(result['status'], 'simulated_only')
        self.assertEqual(self.port.writes, 2)
        self.assertEqual(len(result['steps']), 2)
        self.assertEqual([step['native_type'] for step in result['steps']], ['ProfileFeature', 'Boss'])
        self.assertFalse(result['delivery_accepted'])

    def test_save_failure_reports_stage_without_blaming_verified_feature(self):
        with patch.object(self.port,'save_reopen',side_effect=RuntimeError('injected save error')):
            result=self.run_plan()
        self.assertEqual(result['failed_stage'],'save_reopen')
        self.assertIsNone(result['failed_feature'])
        self.assertEqual(len(result['steps']),2)
        self.assertEqual(result['rollback']['state'],'RESTORED')

    def test_failure_halfway_restores_actual_bytes_and_reopen_snapshot(self):
        self.port.fail_after = 2
        result = self.run_plan()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed_feature']['id'], example()['features'][1]['id'])
        self.assertIn('Traceback (most recent call last)',result['traceback'])
        self.assertEqual(result['rollback']['state'], 'RESTORED')
        self.assertEqual(self.port.path.read_bytes(), self.port.initial)
        self.assertEqual(self.port.writes, 2)

    def test_bad_native_body_and_bad_persisted_readback_both_roll_back(self):
        for flag in ('bad_body', 'bad_reopen'):
            with self.subTest(flag=flag):
                with tempfile.TemporaryDirectory() as root:
                    self.port = BytePort(Path(root)); setattr(self.port, flag, True)
                    result = self.run_plan()
                    self.assertEqual(result['rollback']['state'], 'RESTORED')
                    self.assertEqual(self.port.path.read_bytes(), self.port.initial)

    def test_failed_close_preserves_work_file_and_quarantines(self):
        self.port.fail_after = 2; self.port.foreign = True
        result = self.run_plan()
        self.assertEqual(result['rollback']['state'], 'ROLLBACK_UNCONFIRMED')
        self.assertEqual(self.port.quarantined, 'ROLLBACK_UNCONFIRMED')
        self.assertNotEqual(self.port.path.read_bytes(), self.port.initial)

    def test_stale_revision_prevents_checkpoint_and_native_writes(self):
        plan = example()
        with self.assertRaises(RevisionConflict):
            run_transaction(plan, self.port, expected_revision='0' * 64, reviewed_plan_sha256=digest(plan))
        self.assertEqual(self.port.writes, 0); self.assertEqual(self.port.checkpoints, 0)

    def test_altered_reviewed_plan_prevents_checkpoint(self):
        plan = example()
        with self.assertRaises(ValueError):
            run_transaction(plan, self.port, expected_revision=self.port.revision(), reviewed_plan_sha256='0' * 64)
        self.assertEqual(self.port.checkpoints, 0)

    def test_mid_transaction_foreign_edit_is_quarantined_without_clobbering_it(self):
        original_record = self.port.record
        def record(phase, value):
            original_record(phase, value)
            if phase == 'feature_verified':
                self.port.state['manual_edit'] = 'preserve me'; self.port.persist()
        self.port.record = record
        result = self.run_plan()
        self.assertEqual(self.port.writes, 1)
        self.assertEqual(result['rollback']['state'], 'OUTCOME_UNKNOWN')
        self.assertIn(b'preserve me', self.port.path.read_bytes())

    def test_unapproved_native_macro_feature_type_rolls_back(self):
        old = self.port.create_feature
        def create(feature):
            old(feature)
            self.port.state['features'][-1]['native_type'] = 'MacroFeature'
        self.port.create_feature = create
        result = self.run_plan()
        self.assertEqual(result['rollback']['state'], 'RESTORED')
        self.assertEqual(result['native_type'], 'MacroFeature')
        self.assertIn('MacroFeature', result['error'])

    def test_sw2022_boss_type_strings_are_accepted_and_recorded_raw(self):
        from modeling_domain.transaction import native_type_accepted
        for name in ('Boss', 'BossExtrude', 'Extrude', 'Extrusion', 'Boss-Extrude',
                     '凸台-拉伸', '凸台拉伸', '基体-拉伸', '基体拉伸', '拉伸', '凸台/拉伸'):
            self.assertTrue(native_type_accepted('extrude', name), name)
        self.assertFalse(native_type_accepted('extrude', 'MacroFeature'))
        self.assertFalse(native_type_accepted('extrude', 'Cut'))
        self.assertFalse(native_type_accepted('cut', 'Extrusion'))
        old = self.port.create_feature
        def create(feature):
            old(feature)
            if feature['kind'] == 'extrude':
                self.port.state['features'][-1]['native_type'] = 'Extrusion'
                self.port.persist()
        self.port.create_feature = create
        result = self.run_plan()
        self.assertEqual(result['status'], 'simulated_only')
        extrude = next(step for step in result['steps'] if step['kind'] == 'extrude')
        self.assertEqual(extrude['native_type'], 'Extrusion')

    def test_observation_restores_camera_and_binds_exact_image_and_revision(self):
        revision = self.port.revision()
        report = observe(self.port, expected_revision=revision, directory=self.root / 'observation')
        self.assertEqual(self.port.camera, 'original')
        self.assertEqual(report['image_sha256'], digest_file(self.root / 'observation/observation.bmp'))
        self.assertEqual(report['revision'], revision)
        self.assertEqual(report['visual_state'], 'reviewing')
        self.assertEqual(json.loads((self.root / 'observation/observation.json').read_bytes()), report)

    def test_failed_capture_also_restores_camera_and_publishes_no_report(self):
        self.port.image_failure = True
        with self.assertRaisesRegex(RuntimeError, 'image failed'):
            observe(self.port, expected_revision=self.port.revision(), directory=self.root / 'observation')
        self.assertEqual(self.port.camera, 'original')
        self.assertFalse((self.root / 'observation/observation.json').exists())

    def test_camera_restore_failure_quarantines_and_publishes_no_report(self):
        self.port.restore_camera_ok = False
        with self.assertRaisesRegex(RuntimeError, 'restoration'):
            observe(self.port, expected_revision=self.port.revision(), directory=self.root / 'observation')
        self.assertEqual(self.port.quarantined, 'OUTCOME_UNKNOWN')
        self.assertFalse((self.root / 'observation/observation.json').exists())

    def test_three_state_clearance_never_interprets_failure_or_touch_as_zero_gap(self):
        self.port.state['bodies'] = [{'name': 'AI_Left'}, {'name': 'AI_Right'}]
        cases = [(0, 5, 'separated'), (20, 0, 'interfering'), (0, 0, 'unknown'),
                 (None, None, 'unknown'), (-1, 0, 'unknown'), (20, 5, 'unknown')]
        for volume, distance, expected in cases:
            with self.subTest(volume=volume, distance=distance):
                self.port.measurement = {'status': 'measured', 'intersection_volume_mm3': volume, 'distance_mm': distance}
                result = body_clearance(self.port, 'AI_Left', 'AI_Right', expected_revision=self.port.revision())
                self.assertEqual(result['state'], expected)
                self.assertFalse(result['engineering_accepted'])
        self.port.intersection_on_copies = lambda *args: (_ for _ in ()).throw(RuntimeError('Boolean failed'))
        result = body_clearance(self.port, 'AI_Left', 'AI_Right', expected_revision=self.port.revision())
        self.assertEqual(result['state'], 'unknown'); self.assertIsNone(result['distance_mm'])


if __name__ == '__main__':unittest.main()
