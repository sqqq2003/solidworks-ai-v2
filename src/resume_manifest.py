"""Content-bound batch resume evidence. This is not engineering acceptance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fingerprint(source: Path, parameters: dict, code_root: Path) -> str | None:
    """Missing input evidence disables resume rather than trusting an old file."""
    try:
        source_hash = sha256(source)
        # Nested COM adapters and feature modules affect saved results too.
        code = {p.relative_to(code_root).as_posix(): sha256(p)
                for p in sorted(code_root.rglob('*.py')) if '__pycache__' not in p.parts}
        payload = json.dumps(dict(schema=1, source=source_hash, parameters=parameters,
                                  code=code), sort_keys=True, allow_nan=False)
        return hashlib.sha256(payload.encode()).hexdigest()
    except (OSError, ValueError, TypeError):
        return None


def record_path(canonical: Path) -> Path:
    return canonical.with_name(canonical.name + '.resume.json')


def verified_output(canonical: Path, expected: str | None) -> Path | None:
    if expected is None:
        return None
    try:
        record = json.loads(record_path(canonical).read_text(encoding='utf-8'))
        if not isinstance(record, dict):
            return None
        if record.get('schema') != 1 or record.get('fingerprint') != expected or record.get('status') != 'passed':
            return None
        name = record['output_name']
        if not isinstance(name, str) or not name or '/' in name or '\\' in name or ':' in name or name in {'.', '..'}:
            return None
        output = canonical.parent / name
        if output.is_symlink() or output.suffix.casefold() != '.sldprt':
            return None
        if output.stat().st_size <= 0 or sha256(output) != record['output_sha256']:
            return None
        return output
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_record(canonical: Path, output: Path, key: str | None, status: str) -> bool:
    """Atomically replace metadata only; never overwrite a CAD artifact."""
    if key is None or status not in {'passed', 'degraded'}:
        return False
    temporary = None
    try:
        if output.parent.resolve() != canonical.parent.resolve() or output.is_symlink() or output.stat().st_size <= 0:
            return False
        data = dict(schema=1, fingerprint=key, status=status,
                    output_name=output.name, output_sha256=sha256(output),
                    engineering_accepted=False)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=canonical.parent,
                                         prefix='.resume-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, record_path(canonical))
        return True
    except (OSError, ValueError, TypeError):
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
