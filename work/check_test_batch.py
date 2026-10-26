"""Audit a whole native test batch without launching CAD or executing commands."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from test_batch_intake import audit_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--out', type=Path, help='optional fresh summary JSON; never overwritten')
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
        result = audit_batch(manifest, args.manifest.parent)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.out:
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(text)
        print(text, end='')
        return 0 if result['status'] == 'evidence_consistent' else 3
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps(dict(status='review_required', error=str(error), cad_executed=False), ensure_ascii=False))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
