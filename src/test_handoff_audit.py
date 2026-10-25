"""Read-only cross-version test handoff audit. Never certifies native geometry."""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

STATES = {'passed', 'degraded', 'failed', 'review_required'}


def _ids(rows, label):
    result = {}
    for row in rows:
        key = row.get('id')
        if not isinstance(key, str) or not key or key in result:
            raise ValueError(f'invalid/duplicate {label} id: {key!r}')
        result[key] = row
    return result


def validate_matrix(matrix):
    if matrix.get('schema_version') != 1:
        raise ValueError('unsupported matrix schema')
    lanes = _ids(matrix.get('lanes', []), 'lane')
    if not lanes:
        raise ValueError('empty test matrix')
    for lane in lanes.values():
        if not re.fullmatch(r'[0-9a-f]{40}', lane.get('sha', '')):
            raise ValueError('full lowercase commit SHA required')
        checks = _ids(lane.get('checks', []), 'check')
        if not checks:
            raise ValueError('empty lane checks')
        for check in checks.values():
            if check.get('scope') not in {'offline', 'native'}:
                raise ValueError('scope must be offline or native')
    return lanes


def audit_handoff(matrix, submission, evidence_root):
    """Compare explicit normalized records; root files are read, never executed.

    'passed' means declared coverage and integrity are coherent, not independent
    CAD/engineering acceptance. Raw runner reports need explicit normalization.
    """
    lanes = validate_matrix(matrix)
    if submission.get('schema_version') != 1:
        raise ValueError('unsupported submission schema')
    root = Path(evidence_root).resolve(strict=True)
    rows = submission.get('results', [])
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError('results must be records')
    expected = {(lid, c['id']) for lid, lane in lanes.items() for c in lane['checks']}
    unexpected = [{'lane': r.get('lane'), 'id': r.get('id')} for r in rows
                  if (r.get('lane'), r.get('id')) not in expected]
    reports = []
    for lid, lane in lanes.items():
        for check in lane['checks']:
            matches = [r for r in rows if r.get('lane') == lid and r.get('id') == check['id']]
            errors, failures, artifacts = [], [], []
            if len(matches) != 1:
                errors.append('missing_result' if not matches else 'duplicate_result')
            else:
                row = matches[0]
                if row.get('sha') != lane['sha']:
                    errors.append('commit_mismatch')
                state = row.get('status')
                if state not in STATES:
                    errors.append('invalid_status')
                elif state == 'failed':
                    failures.append('runner_reported_failure')
                elif state == 'review_required':
                    errors.append('runner_requires_review')
                if row.get('scope') != check['scope']:
                    errors.append('scope_mismatch')
                if check['scope'] == 'native':
                    if row.get('environment', {}).get('platform') != 'Windows' or not row.get('environment', {}).get('solidworks_version'):
                        errors.append('missing_native_environment')
                    if type(row.get('process_exit_code')) is not int:
                        errors.append('unobserved_process_exit')
                    elif row['process_exit_code'] != 0:
                        failures.append('nonzero_process_exit')
                declared = row.get('artifacts', [])
                if not isinstance(declared, list) or not declared:
                    errors.append('missing_artifacts')
                    declared = []
                names = set()
                for item in declared:
                    name, digest = item.get('path'), item.get('sha256')
                    if not isinstance(name, str) or not name or '\\' in name or ':' in name or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                        errors.append('unsafe_artifact_path')
                        continue
                    if name in names:
                        errors.append('duplicate_artifact')
                    names.add(name)
                    path = (root / name).resolve()
                    if not path.is_relative_to(root) or not path.is_file():
                        errors.append('missing_or_external_artifact')
                        continue
                    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                        errors.append('invalid_artifact_hash')
                        continue
                    hasher = hashlib.sha256()
                    with path.open('rb') as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            hasher.update(block)
                    actual = hasher.hexdigest()
                    artifacts.append({'path': name, 'sha256': actual, 'matches': actual == digest})
                    if actual != digest:
                        failures.append('artifact_hash_mismatch')
            status = 'failed' if failures else 'review_required' if errors else ('degraded' if matches[0]['status'] == 'degraded' else 'passed')
            reports.append({'lane': lid, 'id': check['id'], 'sha': lane['sha'], 'status': status,
                            'issues': sorted(set(failures + errors)), 'artifacts': artifacts})
    counts = {s: sum(r['status'] == s for r in reports) for s in sorted(STATES)}
    status = 'failed' if counts['failed'] else 'review_required' if counts['review_required'] or unexpected else 'degraded' if counts['degraded'] else 'passed'
    return {'schema_version': 1, 'status': status, 'counts': counts, 'results': reports,
            'unexpected_results': unexpected, 'native_acceptance': 'requires_independent_review',
            'manufacturing_approved': False, 'scope': 'declared_coverage_and_file_integrity_only'}
