"""Bounded modeling writes, revision-bound observation and honest clearance."""
import math
from pathlib import Path

from cad_checkpoint import digest_file
from drawing_review import atomic_json
from .contract import analyze_draft, edit_compatibility, verify_bodies


class RevisionConflict(RuntimeError):
    pass


def require_revision(port, expected_revision):
    if (not isinstance(expected_revision, str) or len(expected_revision) != 64
            or any(c not in '0123456789abcdef' for c in expected_revision)):
        raise ValueError('expected_revision SHA256 required')
    actual = port.revision()
    if actual != expected_revision:
        raise RevisionConflict('REVISION_CONFLICT: document changed since analysis/observation')
    return actual


def feature_map(inventory):
    rows = inventory['features']
    result = {r['name']: r['native_type'] for r in rows}
    if len(result) != len(rows):
        raise RuntimeError('duplicate native feature names')
    return result


NATIVE_TYPES = {'sketch': {'ProfileFeature'}, 'extrude': {'Boss', 'BossExtrude'},
                'cut': {'Cut', 'CutExtrude'}, 'revolve': {'Revolution', 'RevBoss'}}


def run_transaction(plan, port, *, expected_revision, reviewed_plan_sha256):
    require_revision(port, expected_revision)
    draft = analyze_draft(plan, revision=expected_revision, inventory=port.inventory())
    if draft['status'] != 'draft_ready' or draft['plan_sha256'] != reviewed_plan_sha256:
        raise ValueError('reviewed draft and conflict-free plan required')
    require_revision(port, expected_revision)
    baseline = port.checkpoint()
    current = port.revision()
    expected_features = feature_map(port.inventory())
    steps, owned = [], []
    try:
        for feature in draft['plan']['features']:
            require_revision(port, current)
            before = port.inventory()
            if feature_map(before) != expected_features:
                raise RevisionConflict('feature inventory changed before native write')
            if feature['id'] in expected_features:
                raise ValueError('owned feature name collision')
            # Check again immediately before the guarded write, after inventory.
            require_revision(port, current)
            port.guard()
            port.create_feature(feature)
            port.rebuild()
            inventory = port.inventory()
            actual = feature_map(inventory)
            if set(actual) != set(expected_features) | {feature['id']}:
                raise RuntimeError('native feature set differs from append-only plan')
            if any(actual[n] != t for n, t in expected_features.items()):
                raise RuntimeError('protected native feature type changed')
            if actual[feature['id']] not in NATIVE_TYPES[feature['kind']]:
                raise RuntimeError('created feature has unapproved native type')
            if feature['kind'] != 'sketch':
                port.name_bodies(feature['expected']['body_names'])
                inventory = port.inventory()
                verification = verify_bodies(inventory['bodies'], feature['expected'])
            else:
                if inventory['bodies'] != before['bodies']:
                    raise RuntimeError('sketch unexpectedly changed solid bodies')
                verification = {'sketch_only': True, 'engineering_accepted': False}
            expected_features = actual
            owned.append(feature['id'])
            current = port.revision()
            steps.append({'feature': feature['id'], 'kind': feature['kind'],
                          'revision': current, 'verification': verification})
            port.record('feature_verified', {'step': steps[-1]})
        require_revision(port, current)
        port.save_reopen()
        final = port.inventory()
        if feature_map(final) != expected_features:
            raise RuntimeError('saved feature inventory differs')
        verify_bodies(final['bodies'], draft['plan']['features'][-1]['expected'])
        result = {'status': 'simulated_only' if port.simulated else 'native_readback_pending_review',
                  'domain': 'modeling', 'revision': port.revision(), 'steps': steps, 'inventory': final,
                  'edit_compatibility': edit_compatibility(final, owned),
                  'simulated_only': port.simulated, 'delivery_accepted': False, 'manufacturing_approved': False}
        port.record('transaction_completed', result)
        return result
    except BaseException as error:
        result = {'status': 'failed', 'error': type(error).__name__ + ': ' + str(error),
                  'steps': steps, 'simulated_only': port.simulated,
                  'delivery_accepted': False, 'manufacturing_approved': False}
        if isinstance(error, RevisionConflict):
            # A foreign/manual edit is not authority to overwrite that edit.
            result['rollback'] = {'state': 'OUTCOME_UNKNOWN', 'reason': 'revision_conflict_requires_reconcile'}
            port.quarantine('OUTCOME_UNKNOWN')
        else:
            try:
                result['rollback'] = port.restore(baseline)
                if result['rollback'].get('state') != 'RESTORED':
                    raise RuntimeError('rollback did not prove restoration')
            except Exception as recovery:
                result['rollback'] = {'state': 'ROLLBACK_UNCONFIRMED', 'error': str(recovery)}
                port.quarantine('ROLLBACK_UNCONFIRMED')
        port.record('transaction_failed', result)
        return result


def observe(port, *, expected_revision, directory, camera='isometric'):
    if camera not in {'front', 'top', 'right', 'isometric'}:
        raise ValueError('camera outside observation whitelist')
    require_revision(port, expected_revision)
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=False)
    prior = port.capture_camera()
    try:
        port.set_camera(camera)
        image = root / 'observation.bmp'
        port.capture_image(image)
        if not image.is_file() or not image.stat().st_size or image.read_bytes()[:2] != b'BM':
            raise RuntimeError('native observation BMP missing or invalid')
    finally:
        try:
            port.restore_camera(prior)
            if not port.camera_matches(prior):
                raise RuntimeError('observation camera restoration not verified')
        except BaseException:
            port.quarantine('OUTCOME_UNKNOWN')
            raise
    require_revision(port, expected_revision)
    inventory = port.inventory()
    require_revision(port, expected_revision)
    report = {'schema_version': 1, 'kind': 'model_observation', 'revision': expected_revision,
              'camera': camera, 'camera_restored': True, 'image_sha256': digest_file(image),
              'image': image.name, 'inventory': inventory, 'simulated_only': port.simulated,
              'visual_state': 'reviewing', 'delivery_accepted': False, 'manufacturing_approved': False}
    atomic_json(root / 'observation.json', report, exclusive=True)
    return report


def body_clearance(port, left, right, *, expected_revision, tolerance_mm=.01):
    require_revision(port, expected_revision)
    if left == right or type(tolerance_mm) not in (int, float) or not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError('distinct bodies and positive finite tolerance required')
    names = {r['name'] for r in port.inventory()['bodies']}
    if not {left, right} <= names:
        raise ValueError('named body absent')
    require_revision(port, expected_revision)
    try:
        result = port.intersection_on_copies(left, right)
        volume, distance = result.get('intersection_volume_mm3'), result.get('distance_mm')
        if result.get('status') != 'measured' or any(
                type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in (volume, distance)):
            raise RuntimeError('Boolean/distance result unavailable')
        if volume > 1e-8 and distance > tolerance_mm:
            raise RuntimeError('Boolean and closest distance contradict each other')
        state = 'interfering' if volume > 1e-8 else 'separated' if distance > tolerance_mm else 'unknown'
        measured = {'state': state, 'intersection_volume_mm3': volume, 'distance_mm': distance,
                    'reason': 'contact_or_tolerance_ambiguous' if state == 'unknown' else 'measured'}
    except Exception as error:
        measured = {'state': 'unknown', 'intersection_volume_mm3': None, 'distance_mm': None,
                    'error': type(error).__name__ + ': ' + str(error)}
    require_revision(port, expected_revision)
    return {'left': left, 'right': right, 'revision': expected_revision, **measured,
            'simulated_only': port.simulated, 'scope': 'separated_interfering_unknown',
            'engineering_accepted': False, 'manufacturing_approved': False}
