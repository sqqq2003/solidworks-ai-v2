"""Hash-bound sheet review documents shared by UI, CLI and future AI adapters.

This module prepares and validates plans only. A recorded confirmation is a
local review claim, not authentication or permission to execute a CAD writer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from parameter_ledger import Parameter, ParameterLedger, digest

MAX_MANIFEST_BYTES = 8 * 1024 * 1024


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _code_hashes():
    root = Path(__file__).resolve().parent
    return {p.relative_to(root).as_posix(): file_hash(p)
            for p in sorted(root.rglob('*.py')) if '__pycache__' not in p.parts}


def create_manifest(source, *, report=None):
    from sheet_batch_review import inspect_sheet_batch
    report = inspect_sheet_batch(source) if report is None else report
    if (Path(source).resolve(strict=True) != Path(report['source']).resolve(strict=True)
            or file_hash(source) != report['source_sha256']):
        raise ValueError('review report source changed; inspect the current drawing again')
    parts = []
    for row in report['candidates']:
        key = f"profile-{row['profile_index'] + 1}"
        ledger = ParameterLedger(report['source_sha256'])
        if row.get('quantity_source'):
            ledger.parameters['quantity'] = Parameter('quantity', row['quantity'], 'count',
                'drawing_text', row['quantity_source'], minimum=1)
        if row.get('thickness_mm') is not None:
            ledger.parameters['thickness'] = Parameter('thickness', row['thickness_mm'], 'mm',
                'drawing_text', row.get('thickness_source') or 'drawing thickness candidate', minimum=.01)
        ledger.parameters['scale'] = Parameter('scale', 1.0, 'ratio', 'template',
            'unchanged geometry proposal; requires explicit confirmation', minimum=.001, maximum=1000)
        ledger.parameters['hole_policy'] = Parameter('hole_policy', 'scale_all', 'text', 'template',
            'default proposal; scale_all or preserve_circle_diameter')
        parts.append({'id': key, 'profile_index': row['profile_index'], 'label': row['label'],
            'bounds_mm': row['bounds_mm'], 'bend_indices': list(row['bend_indices']),
            'text_frame': bool(row['text_frame']), 'included': False,
            'selection_review': None, 'ledger': ledger.to_dict()})
    return {'schema_version': 1, 'kind': 'sheet_batch_review',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source': report['source'], 'source_sha256': report['source_sha256'],
        'code_sha256': _code_hashes(), 'parts': parts, 'warnings': report['warnings'],
        'native_write_allowed': False, 'production_approved': False,
        'validation': {'status': 'not_run', 'reason': 'review document only'}}


def _part(manifest, part_id):
    matches = [p for p in manifest['parts'] if p['id'] == part_id]
    if len(matches) != 1:
        raise ValueError('unique part identity required')
    return matches[0]


def part_digest(part):
    return digest({k: part[k] for k in ('id', 'profile_index', 'bounds_mm',
                                       'bend_indices', 'text_frame', 'included', 'ledger')})


def set_parameter(manifest, part_id, *, key, value, source, actor):
    """Record an explicit reviewed value and invalidate part selection review."""
    if key not in {'quantity', 'thickness', 'radius', 'angle', 'k_factor', 'scale', 'hole_policy'}:
        raise ValueError('unsupported sheet parameter')
    unit, lower, upper = {
        'quantity': ('count', 1, None), 'thickness': ('mm', .01, None),
        'radius': ('mm', .001, None), 'angle': ('deg', .001, 179.999),
        'k_factor': ('ratio', 0, 1), 'scale': ('ratio', .001, 1000),
        'hole_policy': ('text', None, None),
    }[key]
    if key == 'hole_policy' and value not in {'scale_all', 'preserve_circle_diameter'}:
        raise ValueError('unsupported hole policy')
    part = _part(manifest, part_id)
    ledger = ParameterLedger.from_dict(part['ledger'])
    ledger.parameters[key] = Parameter(key, value, unit, 'user', source,
                                       minimum=lower, maximum=upper)
    ledger.confirm(key, actor)
    part['ledger'] = ledger.to_dict()
    part['selection_review'] = None


def select_part(manifest, part_id, *, included, actor, reason):
    if type(included) is not bool or not actor.strip() or not reason.strip():
        raise ValueError('explicit selection, reviewer and reason required')
    part = _part(manifest, part_id)
    if included and part['text_frame']:
        raise ValueError('text-frame candidate cannot enter native part generation')
    part['included'] = included
    part['selection_review'] = {'actor': actor, 'reason': reason,
        'reviewed_at': datetime.now(timezone.utc).isoformat(), 'part_sha256': part_digest(part)}


def validate_manifest(manifest, *, source=None, check_code=True):
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or manifest.get('kind') != 'sheet_batch_review':
        raise ValueError('unsupported batch review document')
    blockers, selected = [], []
    path = Path(source or manifest['source']).resolve(strict=True)
    if file_hash(path) != manifest['source_sha256']:
        blockers.append('source_changed')
    if check_code and manifest.get('code_sha256') != _code_hashes():
        blockers.append('code_changed_recreate_review')
    parts = manifest.get('parts')
    if not isinstance(parts, list) or len(parts) > 10000:
        raise ValueError('bounded parts list required')
    identifiers, indices = set(), set()
    for part in parts:
        identity = part['id']
        if identity in identifiers or part['profile_index'] in indices:
            raise ValueError('duplicate part or profile identity')
        identifiers.add(identity)
        indices.add(part['profile_index'])
        if type(part['included']) is not bool or type(part['text_frame']) is not bool:
            raise ValueError('explicit boolean selection required')
        bounds = part['bounds_mm']
        if len(bounds) != 4 or not all(type(v) in (int, float) and math.isfinite(v) for v in bounds):
            raise ValueError('finite four-value bounds required')
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            raise ValueError('positive profile envelope required')
        review = part.get('selection_review')
        if not isinstance(review, dict) or not review.get('actor') or not review.get('reason') or review.get('part_sha256') != part_digest(part):
            blockers.append(identity + ':selection_review_missing_or_stale')
        ledger = ParameterLedger.from_dict(part['ledger'])
        if ledger.source_sha256 != manifest['source_sha256']:
            blockers.append(identity + ':parameter_source_changed')
        if not part['included']:
            continue
        selected.append(identity)
        if part['text_frame']:
            blockers.append(identity + ':text_frame')
        required = ['quantity', 'thickness', 'scale', 'hole_policy']
        if part['bend_indices']:
            required += ['radius', 'angle', 'k_factor']
        blockers.extend(identity + ':' + key for key in ledger.blockers(required))
    if not selected:
        blockers.append('no_selected_parts')
    return {'status': 'review_complete_pending_validation' if not blockers else 'blocked',
        'blockers': sorted(set(blockers)), 'selected_parts': selected,
        'review_sha256': digest(manifest), 'native_write_allowed': False,
        'cad_executed': False, 'production_approved': False,
        'validation': 'not_run'}


def save_manifest(manifest, destination):
    """Exclusive creation: never replace an existing review or customer file."""
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if len(payload.encode('utf-8')) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest exceeds size limit')
    with Path(destination).open('x', encoding='utf-8') as stream:
        stream.write(payload)


def load_manifest(path):
    path = Path(path)
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError('manifest exceeds size limit')
    return json.loads(path.read_text(encoding='utf-8'))


def compile_plan_jobs(manifest, *, source=None):
    """Map reviewed candidates to existing planning jobs, never native writes.

    This keeps the workbench as the single execution adapter. A future native
    batch adapter must add document ownership, serialized writes, per-part
    reopen evidence and explicit operation authorization before execution.
    """
    report = validate_manifest(manifest, source=source)
    if report['blockers']:
        return {**report, 'jobs': []}
    jobs = []
    for part in manifest['parts']:
        if not part['included']:
            continue
        ledger = ParameterLedger.from_dict(part['ledger'])
        values = {k: p.value for k, p in ledger.parameters.items()}
        # Planning still requires explicit bend values in the legacy CLI. Flat
        # parts receive no guessed radius/angle/K, so remain blocked until set.
        missing = ledger.blockers(('radius', 'angle', 'k_factor'))
        if missing:
            report['blockers'].extend(part['id'] + ':' + k + ':required_by_plan_adapter' for k in missing)
            continue
        jobs.append({'kind': 'sheet', 'action': 'plan', 'name': part['label'],
            'source': str(Path(source or manifest['source']).resolve()),
            'profile': part['profile_index'] + 1, 'thickness': values['thickness'],
            'radius': values['radius'], 'angle': values['angle'], 'k_factor': values['k_factor'],
            'uniform_scale': values['scale'],
            'preserve_circle_holes': values['hole_policy'] == 'preserve_circle_diameter',
            'confirmed': False})
    return {**report, 'status': 'blocked' if report['blockers'] else 'planned_unverified',
            'jobs': [] if report['blockers'] else jobs}
