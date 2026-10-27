"""Opt-in native reviewed-batch entrypoint; default is read-only preparation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]


def emit(event, **payload):
    print(json.dumps({'event': event, **payload}, ensure_ascii=False, allow_nan=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='已审核钣金批次：默认只规划，显式选择后才生成工作副本')
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--out-dir', type=Path)
    parser.add_argument('--review-sha256')
    parser.add_argument('--sw-exe', type=Path)
    parser.add_argument('--execute-reviewed', action='store_true')
    parser.add_argument('--timeout-seconds', type=float, default=900)
    args = parser.parse_args(argv)
    try:
        from batch_review_manifest import load_manifest
        from parameter_ledger import digest
        from reviewed_batch import prepare_execution, execute_reviewed_batch, _write_receipt
        import math
        if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
            raise ValueError('positive finite timeout required')
        manifest = load_manifest(args.manifest)
        plan = prepare_execution(manifest, source=args.source)
        if not args.execute_reviewed:
            emit('plan', kind='sheet_batch_review', plan=plan, cad_executed=False)
            return 3 if plan['blockers'] else 0
        if plan['blockers']:
            raise ValueError('review blocked: ' + ', '.join(plan['blockers']))
        if args.review_sha256 != digest(manifest):
            raise ValueError('explicit current review SHA256 required for execution')
        if not args.out_dir or args.out_dir.resolve().exists():
            raise ValueError('new dedicated output directory required')
        if sys.platform != 'win32':
            raise RuntimeError('native SolidWorks execution requires Windows')
        if not args.sw_exe or not args.sw_exe.is_file() or args.sw_exe.name.casefold() != 'sldworks.exe':
            raise ValueError('installed SLDWORKS.exe required')
        from sw_owned_launch import owned_solidworks
        from sw_session import run_on_task_sta

        def run():
            receipt = None
            try:
                with owned_solidworks(args.sw_exe) as binding:
                    emit('session', **binding.evidence())
                    receipt = execute_reviewed_batch(manifest, expected_review_sha256=args.review_sha256,
                        output_dir=args.out_dir, source=args.source,
                        progress=lambda message: emit('progress', message=message))
            except Exception as error:
                if receipt is not None:
                    receipt.update(status='saved_pending_session_recovery',
                        session_cleanup_error={'type': type(error).__name__, 'message': str(error)})
                    _write_receipt(args.out_dir.resolve(), receipt)
                raise
            session = binding.evidence()
            receipt['session_end'] = session
            safe_cleanup = session.get('cleanup_status') in {'left_open_keepalive', 'process_exited_cleanly'}
            if not safe_cleanup:
                receipt['status'] = 'saved_pending_session_recovery'
            _write_receipt(args.out_dir.resolve(), receipt)
            emit('session_end', **session)
            emit('done', kind='sheet_batch', status='generated_unverified' if safe_cleanup else 'degraded',
                 receipt=str(args.out_dir.resolve() / 'execution.receipt.json'),
                 total=len(receipt['parts']), unattempted=len(receipt['unattempted']),
                 mechanical_acceptance='unverified', production_approved=False)
            # Uncertain teardown blocks the surrounding workbench queue.
            return 3 if safe_cleanup else 1

        return run_on_task_sta(run, timeout=args.timeout_seconds, task_name='reviewed-sheet-batch')
    except Exception as error:
        from app_logging import get_journal
        get_journal().exception('reviewed_batch_failed', error)
        emit('error', kind='sheet_batch', message=str(error), detail=type(error).__name__,
             production_approved=False)
        return 1


if __name__ == '__main__':
    from app_logging import bootstrap
    bootstrap(ROOT, 'reviewed-batch')
    raise SystemExit(main())
