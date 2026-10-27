"""Explicit before/write/save/reopen geometry observation transaction.

Opt-in native adapter, not live-qualified. No connection, threads or execution
on import; the existing driver supplies the owned STA and document lifecycle.
Failure retains artifacts and never attempts process termination or rollback.
"""
from __future__ import annotations

import math
from pathlib import Path

from geometry_evidence import compare_snapshots, require_check_contract


class PartChangeFailed(RuntimeError):
    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


def change_owned_part(driver, *, source_path, source_sha256, work_copy,
                      document_key, configuration, step_id, checks,
                      dimensions_mm, apply_change):
    """Perform one explicitly reviewed change and compare three snapshots.

    dimensions_mm maps semantic keys to exact native dimension names, with mm
    conversion only. Checks and numerical tolerances come from the caller;
    no generic manufacturing tolerances or approximate geometric matches are
    substituted. A successful observation is still pending engineering review.
    """
    from app_logging import get_journal
    from batch_review_manifest import file_hash
    from native_geometry_snapshot import capture_owned_part
    import solidworks_generator as sw
    require_check_contract(checks)
    if not isinstance(step_id, str) or not step_id.strip() or not callable(apply_change):
        raise ValueError('explicit step id and reviewed change callable required')
    if not isinstance(dimensions_mm, dict) or len(dimensions_mm) > 1000 or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v
            for k, v in dimensions_mm.items()):
        raise ValueError('bounded exact dimension bindings required')
    if any(c['field'].startswith('dimension:') and c['field'][10:] not in dimensions_mm for c in checks):
        raise ValueError('all checked dimensions need native bindings before writing')
    baseline = Path(source_path).resolve(strict=True)
    copy = driver.owned_path(work_copy).resolve(strict=True)
    if baseline.samefile(copy) or baseline.suffix.casefold() != '.sldprt' or copy.suffix.casefold() != '.sldprt':
        raise ValueError('distinct source and native work-copy parts required')
    if file_hash(baseline) != source_sha256:
        raise ValueError('source baseline changed')
    journal = get_journal()
    receipt = {'schema_version': 1, 'step_id': step_id, 'source_sha256': source_sha256,
        'document_key': document_key, 'configuration': configuration, 'work_copy': str(copy),
        'status': 'started', 'cad_write_attempted': False, 'saved': False, 'reopened': False,
        'snapshots': {}, 'comparisons': {}, 'geometry_verified': False, 'production_approved': False}
    model = None

    def activate():
        manager = sw._com_read(model, 'ConfigurationManager')
        active = str(sw._com_read(sw._com_read(manager, 'ActiveConfiguration'), 'Name'))
        if active != configuration and not model.ShowConfiguration2(configuration):
            raise RuntimeError('requested work-copy configuration is unavailable')

    def capture(phase):
        snapshot = capture_owned_part(driver, model, source_path=baseline,
            source_sha256=source_sha256, document_key=document_key,
            configuration=configuration, step_id=step_id, phase=phase)
        for key, name in dimensions_mm.items():
            driver.guard()
            dimension = model.Parameter(name)
            if dimension is None:
                raise RuntimeError('mapped snapshot dimension missing: ' + name)
            value = float(sw._com_read(dimension, 'SystemValue')) * 1000
            if not math.isfinite(value):
                raise RuntimeError('non-finite native dimension readback: ' + name)
            snapshot['dimensions_mm'][key] = value
        receipt['snapshots'][phase] = snapshot
        journal.record('part_transaction_snapshot',step_id=step_id,phase=phase,snapshot=snapshot)
        return snapshot

    def assert_consistent(result):
        if result['status'] != 'observations_consistent_pending_engineering':
            raise RuntimeError('geometry observations failed or remained incomplete')

    try:
        driver.guard()
        model = driver.open_document(copy, configuration)
        activate()
        before = capture('before')
        # Validate and resolve required reads before invoking the change callback.
        compare_snapshots(before, before, checks, step_id=step_id + ':preflight')
        if file_hash(baseline) != source_sha256:
            raise RuntimeError('source changed before dimension write')
        driver.guard()
        receipt['cad_write_attempted'] = True
        journal.record('part_transaction_write_started', step_id=step_id, source_sha256=source_sha256)
        receipt['change_result'] = apply_change(model)
        after = capture('after')
        comparison = compare_snapshots(before, after, checks, step_id=step_id + ':after')
        receipt['comparisons']['after'] = comparison
        assert_consistent(comparison)
        driver.guard()
        driver._save(model)
        receipt['saved'] = True
        receipt['saved_sha256'] = file_hash(copy)
        closing = model
        model = None  # Do not retry CloseDoc if its outcome becomes uncertain.
        driver.close_document(closing)
        driver.guard()
        model = driver.open_document(copy, configuration)
        activate()
        reopened = capture('reopened')
        receipt['reopened'] = True
        comparison = compare_snapshots(before, reopened, checks, step_id=step_id + ':reopened')
        receipt['comparisons']['reopened'] = comparison
        assert_consistent(comparison)
        # Invariance compares the saved result to the reopened result; target or
        # delta checks against the original alone could miss a changed metric.
        invariants = [{'field': c['field'], 'mode': 'unchanged', 'unit': c['unit'],
                       'tolerance': c['tolerance']} for c in checks]
        unique = {}
        for check in invariants:
            key = check['field']
            if key not in unique or check['tolerance'] < unique[key]['tolerance']:
                unique[key] = check
        stability = compare_snapshots(after, reopened, list(unique.values()), step_id=step_id + ':save_stability')
        receipt['comparisons']['save_stability'] = stability
        assert_consistent(stability)
        if file_hash(baseline) != source_sha256 or file_hash(copy) != receipt['saved_sha256']:
            raise RuntimeError('source or saved file changed during reopen observations')
        receipt['status'] = 'observations_consistent_pending_engineering'
        journal.record('part_transaction_observed', step_id=step_id, receipt=receipt)
    except Exception as error:
        receipt.update(status='failed_or_unverified', error={'type': type(error).__name__, 'message': str(error)})
        journal.exception('part_transaction_failed', error, step_id=step_id, receipt=receipt)
        raise PartChangeFailed(str(error), receipt) from error
    finally:
        if model is not None:
            try:
                driver.close_document(model)
            except Exception as error:
                # Never hide a failed cleanup or force-close an unknown document.
                receipt['cleanup_error'] = {'type': type(error).__name__, 'message': str(error)}
                receipt['status'] = 'failed_or_unverified'
                journal.exception('part_transaction_cleanup_failed', error, step_id=step_id)
    if receipt.get('cleanup_error'):
        raise PartChangeFailed('owned work-copy cleanup was not verified', receipt)
    return receipt
