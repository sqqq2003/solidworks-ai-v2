"""Analyze a narrow plan, or run it in one already-open SolidWorks (CloseDoc only)."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('capabilities')
    draft = commands.add_parser('analyze')
    draft.add_argument('plan', type=Path)
    draft.add_argument('--out', type=Path, required=True)
    run = commands.add_parser('run')
    run.add_argument('plan', type=Path)
    run.add_argument('--sw-exe', type=Path, required=True)
    run.add_argument('--template', type=Path, required=True)
    run.add_argument('--expected-template-sha256', required=True)
    run.add_argument('--reviewed-plan-sha256', required=True)
    run.add_argument('--request-key', required=True)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--camera', choices=['front', 'top', 'right', 'isometric'], default='isometric')
    run.add_argument('--clearance', nargs=2, action='append', default=[])
    run.add_argument('--state-db', type=Path)
    args = parser.parse_args(argv)
    try:
        from modeling_domain import analyze_draft, capabilities
        from drawing_review import atomic_json
        if args.command == 'capabilities':
            result = capabilities()
        else:
            plan = json.loads(args.plan.read_text(encoding='utf-8'))
            if args.command == 'analyze':
                result = analyze_draft(plan)
                atomic_json(args.out, result, exclusive=True)
            else:
                from modeling_domain.api import run_native_modeling
                result = run_native_modeling(plan, args.sw_exe, args.template, args.out,
                    expected_template_sha256=args.expected_template_sha256,
                    reviewed_plan_sha256=args.reviewed_plan_sha256, request_key=args.request_key,
                    camera=args.camera, clearance_pairs=args.clearance, state_db=args.state_db)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('status') in {'failed', 'blocked'}:
            return 1
        return 0 if args.command != 'run' else 3  # native readback still needs review
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error),
                          'delivery_accepted': False, 'manufacturing_approved': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
