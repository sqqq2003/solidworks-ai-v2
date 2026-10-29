"""python work/audit_test_handoff.py MATRIX SUBMISSION --evidence-root DIR"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from test_handoff_audit import audit_handoff


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('matrix', type=Path)
    parser.add_argument('submission', type=Path)
    parser.add_argument('--evidence-root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = audit_handoff(json.loads(args.matrix.read_text(encoding='utf-8-sig')),
                               json.loads(args.submission.read_text(encoding='utf-8-sig')), args.evidence_root)
    except (ValueError, OSError, TypeError, AttributeError) as exc:
        print(json.dumps({'status': 'review_required', 'error': str(exc)}, ensure_ascii=False))
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {'passed': 0, 'failed': 1, 'degraded': 2, 'review_required': 3}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
