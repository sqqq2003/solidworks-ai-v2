"""Verify an extracted test bundle before invoking its project code."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(root):
    root = Path(root).resolve()
    data = json.loads((root/'HANDOFF.json').read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not data.get('files'):
        raise ValueError('invalid handoff manifest')
    bad = []
    for name,checksum in data['files'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            bad.append(name)
    return {'status':'verified' if not bad else 'failed','revision':data['revision'],'mismatches':bad,
            'note':'Integrity check is not native CAD acceptance.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder',type=Path)
    args = p.parse_args()
    try:
        report = verify(args.folder)
    except (OSError,ValueError,KeyError) as exc:
        report = {'status':'failed','error':str(exc)}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
