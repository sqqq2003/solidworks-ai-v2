"""Explicit Windows fault: save a half-built owned model, then restore baseline."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--sw-exe', type=Path, required=True)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--expected-template-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--request-key', required=True)
    parser.add_argument('--fault-after-feature', required=True)
    parser.add_argument('--enable-fault-injection', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'win32':
            raise RuntimeError('Windows SolidWorks required; cloud cannot verify this native fault')
        if args.out.exists():
            raise FileExistsError('fault test requires a new output directory')
        from cad_checkpoint import Checkpoint, digest_file, inspect_checkpoint
        from cad_receipts import ReceiptStore
        from drawing_review import atomic_json
        from modeling_domain.api import run_native_modeling
        from modeling_domain.contract import digest, validate_plan
        from modeling_domain.native import NativeModelingPort
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        plan['fault_test'] = {'after_feature': args.fault_after_feature, 'save_before_failure': True}
        validate_plan(plan)
        if args.fault_after_feature not in {f['id'] for f in plan['features']}:
            raise ValueError('fault feature absent from reviewed plan')
        original = NativeModelingPort.create_feature
        triggered = []
        def inject(port, feature):
            original(port, feature)
            if feature['id'] == args.fault_after_feature:
                port.rebuild()
                port._save()
                triggered.append(feature['id'])
                raise RuntimeError('GORK_FAULT_AFTER_SAVED_MODELING_FEATURE:' + feature['id'])
        with patch.object(NativeModelingPort, 'create_feature', inject):
            result = run_native_modeling(plan, args.sw_exe, args.template, args.out,
                expected_template_sha256=args.expected_template_sha256,
                reviewed_plan_sha256=digest(plan), request_key=args.request_key)
        errors = []
        if triggered != [args.fault_after_feature]:errors.append('fault_not_reached_exactly_once')
        if result.get('status') != 'failed' or result.get('rollback', {}).get('state') != 'RESTORED':
            errors.append('rollback_not_confirmed')
        receipt = result.get('request_receipt', {})
        if receipt.get('status') != 'FAILED' or receipt.get('session_state') != 'RESOLVED':
            errors.append('request_unresolved')
        row = ReceiptStore().get(receipt['key'])
        declared = row['metadata']['checkpoint']
        checkpoint = Checkpoint(Path(declared['directory']), declared['manifest_sha256'], Path(declared['scope']))
        manifest = inspect_checkpoint(checkpoint)
        for item in manifest['files']:
            if digest_file(item['target']) != item['source_sha256']:errors.append('work_model_baseline_hash_differs')
        for path, expected in manifest['original_sha256'].items():
            if digest_file(path) != expected:errors.append('template_changed')
        report = {'status': 'failed' if errors else 'review_required', 'errors': errors,
                  'fault_after_feature': args.fault_after_feature, 'triggered': triggered,
                  'rollback': result.get('rollback'), 'request_receipt': receipt,
                  'delivery_accepted': False, 'manufacturing_approved': False}
        atomic_json(args.out / 'modeling-rollback-fault.json', report, exclusive=True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if errors else 3
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error),
                          'delivery_accepted': False, 'manufacturing_approved': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
