"""Byte-exact checkpoints for an explicitly isolated, task-owned CAD file set.

This module never closes a COM document or discovers/deletes CAD files. The
native adapter must prove ownership and close the complete file set first.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import uuid

OWNER = 'solidworks-ai/checkpoint-v1'


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def write_receipt(path, value):
    with Path(path).open('xb') as stream:
        stream.write(json_bytes(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def safe_file(path, root):
    path, root = Path(path).absolute(), Path(root).resolve(strict=True)
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('checkpoint file outside owned scope or not a regular file')
    # Refuse aliasing through symlink parents, even when the final path is inside.
    if path != path.resolve() or path.stat().st_nlink != 1:
        raise ValueError('checkpoint file has an alias')
    return path


@dataclass(frozen=True)
class Checkpoint:
    directory: Path
    manifest_sha256: str
    scope: Path


def create_checkpoint(files, directory, *, scope, snapshot, originals=None):
    """All target documents must be closed under the caller's writer lease.

    Snapshot is JSON data collected from the same saved files, including native
    features and bodies. Original user CAD is hash-only, never a restore target.
    """
    scope = Path(scope).resolve(strict=True)
    files = sorted({safe_file(p, scope) for p in files})
    if not files:
        raise ValueError('empty checkpoint file set')
    if not isinstance(snapshot, dict) or not {'features', 'bodies'} <= snapshot.keys():
        raise ValueError('feature and body snapshots required')
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(directory)
    directory.mkdir(parents=True, exist_ok=False)
    if directory != directory.resolve() or directory.is_relative_to(scope):
        raise ValueError('checkpoint must be separate from isolated CAD scope')
    rows = []
    original_hashes = dict(originals or {})
    for name, expected in original_hashes.items():
        if digest_file(name) != expected:
            raise RuntimeError('original changed before checkpoint')
        if Path(name).resolve().is_relative_to(scope):
            raise ValueError('original user CAD cannot be an isolated restore target')
    for index, path in enumerate(files):
        before = digest_file(path)
        name = f'{index:04d}{path.suffix.lower()}'
        backup = directory / name
        with path.open('rb') as source, backup.open('xb') as copy:
            shutil.copyfileobj(source, copy)
            copy.flush()
            os.fsync(copy.fileno())
        after, copied = digest_file(path), digest_file(backup)
        if before != after or before != copied:
            raise RuntimeError('CAD bytes changed while checkpointing')
        rows.append({'target': str(path), 'backup': name,
                     'source_sha256': before, 'copy_sha256': copied})
    manifest = {'schema_version': 1, 'owner': OWNER, 'checkpoint_id': uuid.uuid4().hex,
                'scope': str(scope), 'files': rows, 'original_sha256': original_hashes,
                'snapshot': snapshot}
    write_receipt(directory / 'manifest.json', manifest)
    checkpoint = Checkpoint(directory, digest_file(directory / 'manifest.json'), scope)
    inspect_checkpoint(checkpoint)
    return checkpoint


def inspect_checkpoint(checkpoint):
    directory = Path(checkpoint.directory).absolute()
    if directory.is_symlink() or directory != directory.resolve(strict=True):
        raise ValueError('checkpoint directory alias')
    manifest_path = safe_file(directory / 'manifest.json', directory)
    if digest_file(manifest_path) != checkpoint.manifest_sha256:
        raise ValueError('checkpoint manifest changed')
    manifest = json.loads(manifest_path.read_bytes())
    if (manifest.get('owner') != OWNER or manifest.get('schema_version') != 1 or
            manifest.get('scope') != str(Path(checkpoint.scope).resolve(strict=True))):
        raise ValueError('foreign checkpoint manifest')
    if not manifest.get('files'):
        raise ValueError('empty checkpoint manifest')
    targets, names = set(), set()
    for row in manifest['files']:
        target = safe_file(row['target'], checkpoint.scope)
        name = row['backup']
        if Path(name).name != name or name in {'manifest.json', 'rollback.json'} or name in names:
            raise ValueError('invalid checkpoint backup name')
        if str(target).casefold() in targets:
            raise ValueError('duplicate checkpoint target')
        targets.add(str(target).casefold()); names.add(name)
        backup = safe_file(directory / name, directory)
        if (row['source_sha256'] != row['copy_sha256'] or
                digest_file(backup) != row['copy_sha256']):
            raise ValueError('checkpoint backup changed')
    return manifest


def equivalent(actual, expected):
    """Tolerate native measurement roundoff, never feature/count/type changes."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(equivalent(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(equivalent(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, float):
        return math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-7)
    return actual == expected


def restore_checkpoint(checkpoint, adapter):
    """Close owned targets, replace bytes, reopen and verify native snapshots.

    An exception is ROLLBACK_UNCONFIRMED, even if some bytes were restored.
    There is deliberately no fallback to closing a foreign/unknown ActiveDoc.
    """
    manifest = inspect_checkpoint(checkpoint)
    targets = [row['target'] for row in manifest['files']]
    for name, expected in manifest['original_sha256'].items():
        if digest_file(name) != expected:
            raise RuntimeError('original user CAD changed; restore refused')
    adapter.close_for_restore(targets)
    adapter.assert_closed(targets)
    for row in manifest['files']:
        target = safe_file(row['target'], checkpoint.scope)
        adapter.assert_closed(targets)
        fd, temporary = tempfile.mkstemp(prefix='.cad-restore-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as output, (checkpoint.directory / row['backup']).open('rb') as source:
                shutil.copyfileobj(source, output)
                output.flush(); os.fsync(output.fileno())
            if digest_file(temporary) != row['source_sha256']:
                raise RuntimeError('restore temporary bytes differ')
            os.replace(temporary, target)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
    actual = json.loads(json_bytes(adapter.reopen_snapshot()))
    if not equivalent(actual, manifest['snapshot']):
        raise RuntimeError('restored native snapshot differs')
    adapter.assert_closed(targets)
    for row in manifest['files']:
        if digest_file(row['target']) != row['source_sha256']:
            raise RuntimeError('restored bytes changed during reopen')
    for name, expected in manifest['original_sha256'].items():
        if digest_file(name) != expected:
            raise RuntimeError('original user CAD changed during restore')
    result = {'state': 'RESTORED', 'manifest_sha256': checkpoint.manifest_sha256,
              'bytes_verified': True, 'reopen_snapshot_verified': True,
              'manufacturing_approved': False}
    write_receipt(checkpoint.directory / 'rollback.json', result)
    return result


def remove_checkpoint(checkpoint):
    """Explicit cleanup of one sealed checkpoint; never scan a CAD directory."""
    manifest = inspect_checkpoint(checkpoint)
    names = {row['backup'] for row in manifest['files']} | {'manifest.json'}
    if (checkpoint.directory / 'rollback.json').exists():
        safe_file(checkpoint.directory / 'rollback.json', checkpoint.directory)
        names.add('rollback.json')
    if {p.name for p in checkpoint.directory.iterdir()} != names:
        raise ValueError('unlisted files in checkpoint; nothing deleted')
    for name in sorted(names - {'manifest.json'}):
        (checkpoint.directory / name).unlink()
    (checkpoint.directory / 'manifest.json').unlink()
    checkpoint.directory.rmdir()
