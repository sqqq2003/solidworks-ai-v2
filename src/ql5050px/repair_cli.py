"""Offline repair preparation CLI. This entry point never attaches to CAD."""
import argparse
import hashlib
import json
from pathlib import Path

from .repair_planning import plan_slot_relief, require_trial
from .step_preservation import StepDocument


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan-slot', help='prepare a trial plan from measured local-frame inputs')
    plan.add_argument('--source', required=True)
    plan.add_argument('--spec', required=True)
    plan.add_argument('--output', required=True)
    validate = commands.add_parser('validate-plan', help='recompute all gates against the current source hash')
    validate.add_argument('--source', required=True)
    validate.add_argument('--plan', required=True)
    prune = commands.add_parser('prune-step', help='apply an explicit reviewed occurrence edit manifest')
    prune.add_argument('--source', required=True)
    prune.add_argument('--manifest', required=True)
    prune.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        data = Path(args.source).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if args.command == 'plan-slot':
            spec = read_json(args.spec)
            if spec.get('source_sha256') != digest:
                raise ValueError('measured specification source baseline changed')
            result = plan_slot_relief(**spec)
            write_json(args.output, result)
        elif args.command == 'validate-plan':
            require_trial(read_json(args.plan), digest)
            result = {'status': 'trial_plan_valid', 'source_sha256': digest,
                      'cad_executed': False, 'production_approved': False}
        else:
            manifest = read_json(args.manifest)
            if manifest.get('trial_authorized') is not True:
                raise ValueError('explicit trial edit authorization required')
            result = StepDocument(data).remove_occurrence_metadata(
                manifest['removed_entities'], expected_sha256=manifest['source_sha256'],
                output=args.output,detach_axes=manifest.get('detach_axes',()))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(2, f'repair refused: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
