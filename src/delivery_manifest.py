"""Local artifact inventory and separate simulation/native/engineering gates.

No upload, CAD mutation, archive extraction, or automatic production approval.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

STAGES = ('simulation', 'solidworks', 'engineering')
CAD_SUFFIXES = frozenset({'.sldprt', '.sldasm', '.slddrw', '.dwg', '.dxf', '.step', '.stp'})
STATES = frozenset({'passed', 'failed', 'blocked', 'unverified', 'not_applicable'})


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root, relative_paths, *, include_cad=False):
    """Explicit file allowlist, no recursive scanning of customer directories."""
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('artifact root must be a directory')
    if not isinstance(relative_paths, (list, tuple)) or len(relative_paths) > 10000:
        raise ValueError('bounded explicit artifact list required')
    rows, seen = [], set()
    for relative in relative_paths:
        rel = Path(relative)
        if rel.is_absolute() or not rel.parts or '..' in rel.parts:
            raise ValueError('workspace-relative artifact path required')
        path = root / rel
        # Refuse symlink traversal even when the final target happens to be in root.
        cursor = root
        for part in rel.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ValueError('symlink artifacts refused')
        path = path.resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('artifact outside root or not a file')
        canonical = path.relative_to(root).as_posix()
        if canonical.casefold() in seen:
            raise ValueError('duplicate artifact path')
        seen.add(canonical.casefold())
        suffix = path.suffix.casefold()
        if suffix in CAD_SUFFIXES and not include_cad:
            raise ValueError('CAD inventory requires explicit local-only opt-in')
        if (path.name.casefold().startswith('.env') or suffix in {'.key', '.pem'}
                or path.name.casefold() in {'credentials.json', 'secrets.json'}):
            raise ValueError('credential artifact refused')
        before = path.stat()
        checksum = _hash(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('artifact changed during inventory')
        rows.append({'path': canonical, 'sha256': checksum, 'size_bytes': after.st_size,
                     'kind': 'cad' if suffix in CAD_SUFFIXES else 'supporting_file'})
    return rows


def build_delivery(root, relative_paths, *, commit, review_sha256=None, include_cad=False):
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('exact Git commit SHA required')
    artifacts = inventory(root, relative_paths, include_cad=include_cad)
    return {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
        'commit': commit, 'review_sha256': review_sha256, 'artifacts': artifacts,
        'stages': {stage: {'status': 'unverified', 'checks': []} for stage in STAGES},
        'cad_included': any(r['kind'] == 'cad' for r in artifacts),
        'cloud_upload_allowed': False, 'production_approved': False,
        'limitations': ['Inventory hashes demonstrate file identity only.',
                        'Local evidence may contain customer information; review before sharing.']}


def assess_delivery(manifest, root, *, required_checks):
    """Return blockers from caller-supplied evidence claims, never a release token.

    required_checks explicitly maps each stage to required check identifiers.
    Evidence files must be in the hashed artifact inventory. A missing stage,
    empty requirement list or not-applicable claim does not count as passing.
    """
    if manifest.get('schema_version') != 1:
        raise ValueError('unsupported delivery manifest')
    rows = manifest.get('artifacts', [])
    current = inventory(root, [row['path'] for row in rows], include_cad=True)
    blockers = []
    if current != rows:
        blockers.append('artifact_inventory_changed')
    evidence = {row['path']: row['sha256'] for row in current}
    for stage in STAGES:
        required = required_checks.get(stage)
        if not isinstance(required, list) or not required or any(not isinstance(k, str) or not k for k in required):
            blockers.append(stage + ':required_checks_not_defined')
            continue
        record = manifest.get('stages', {}).get(stage, {})
        if record.get('status') != 'passed':
            blockers.append(stage + ':stage_not_passed')
        checks = record.get('checks', [])
        for key in required:
            matches = [r for r in checks if r.get('id') == key]
            if len(matches) != 1:
                blockers.append(stage + ':' + key + ':missing_or_duplicate')
                continue
            check = matches[0]
            if check.get('status') not in STATES:
                raise ValueError('unknown evidence status')
            if check['status'] != 'passed':
                blockers.append(stage + ':' + key + ':not_passed')
            if (not check.get('evidence_path') or not check.get('evidence_sha256')
                    or evidence.get(check['evidence_path']) != check['evidence_sha256']):
                blockers.append(stage + ':' + key + ':evidence_missing_or_changed')
            if check.get('commit') != manifest.get('commit'):
                blockers.append(stage + ':' + key + ':code_baseline_mismatch')
            if not manifest.get('review_sha256') or check.get('review_sha256') != manifest['review_sha256']:
                blockers.append(stage + ':' + key + ':review_baseline_missing_or_changed')
    return {'status': 'blocked' if blockers else 'evidence_claims_match_pending_independent_review',
            'blockers': sorted(set(blockers)), 'production_approved': False,
            'cad_executed': False, 'cloud_upload_allowed': False}
