"""Opt-in Windows fault test: fail after one saved edit in an approved work copy.

Never use an existing production workspace. The normal manifest, named review,
owned launch, permanent claim and receipt admission remain in force.
"""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]


def verify_report(report, checkpoint):
    from cad_checkpoint import digest_file, inspect_checkpoint
    manifest = inspect_checkpoint(checkpoint)
    errors = []
    if report.get('status') != 'failed': errors.append('expected_injected_execution_failure')
    if report.get('rollback', {}).get('state') != 'RESTORED': errors.append('rollback_unconfirmed')
    if report.get('cleanup') != 'owned_documents_closed': errors.append('owned_cleanup_unconfirmed')
    if report.get('request_receipt', {}).get('status') != 'FAILED': errors.append('receipt_not_failed')
    if report.get('request_receipt', {}).get('session_state') != 'RESOLVED': errors.append('session_still_unresolved')
    for row in manifest['files']:
        if digest_file(row['target']) != row['source_sha256']: errors.append('isolated_baseline_differs')
    for path, expected in manifest['original_sha256'].items():
        if digest_file(path) != expected: errors.append('original_source_changed')
    return {'status': 'failed' if errors else 'review_required', 'errors': errors,
            'test_result': 'failed' if errors else 'rollback_verified_requires_independent_review',
            'manifest_sha256': checkpoint.manifest_sha256,
            'manufacturing_approved': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--sw-exe', type=Path, required=True)
    parser.add_argument('--approval-sha256', required=True)
    parser.add_argument('--enable-fault-injection', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'win32': raise RuntimeError('Windows SolidWorks required; no cloud native pass')
        from cad_checkpoint import Checkpoint
        from cad_receipts import ReceiptStore
        from project_delivery import execute_workflow, write_new
        from roller_variant.native import RollerDriver
        original_write = RollerDriver.write
        saved = []
        def fail_after_saved_edit(driver, change):
            original_write(driver, change)
            saved.append(change['parameter'])
            raise RuntimeError('GORK_FAULT_AFTER_FIRST_SAVED_DIMENSION')
        with patch.object(RollerDriver, 'write', fail_after_saved_edit):
            report = execute_workflow(args.workspace, sw_exe=args.sw_exe,
                                      approval_sha256=args.approval_sha256)
        key = report.get('request_receipt', {}).get('key')
        if len(saved) != 1 or not key:
            raise RuntimeError('fault did not reach exactly one saved edit; preserve workspace and receipt')
        row = ReceiptStore().get(key); declared = row['metadata']['checkpoint']
        checkpoint = Checkpoint(Path(declared['directory']), declared['manifest_sha256'], Path(declared['scope']))
        result = verify_report(report, checkpoint)
        result.update(request_key=key, saved_edits=saved, source_revision='record tested commit in Gork submission')
        write_new(args.workspace / 'rollback-fault-test.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['status'] == 'failed' else 3
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc), 'manufacturing_approved': False}, ensure_ascii=False))
        return 1


if __name__ == '__main__': raise SystemExit(main())
