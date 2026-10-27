"""Bridge reviewed sheet manifests to the existing serial owned-session writer.

Native functions are opt-in, Windows-only and unqualified in this code batch.
Importing this module neither connects CAD nor executes a task.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import tempfile

from batch_review_manifest import file_hash, validate_manifest
from parameter_ledger import ParameterLedger, digest


def prepare_execution(manifest, *, source=None):
    """Prepare explicit per-part settings; do not create outputs or launch CAD."""
    from batch_export import discover_sheet_parts, format_sheet_part_name
    from cad_analyzer import analyze_cad_file, primitive_bounds
    report = validate_manifest(manifest, source=source)
    if report['blockers']:
        return {**report, 'entries': []}
    source = Path(source or manifest['source']).resolve(strict=True)
    analysis = analyze_cad_file(source)
    candidates = {j.profile_index: j for j in discover_sheet_parts(analysis)}
    entries, blockers = [], list(report['blockers'])
    expected_indices = {row['profile_index'] for row in manifest['parts']}
    if expected_indices != set(candidates):
        blockers.append('candidate_inventory_changed')
    for part in manifest['parts']:
        current = candidates.get(part['profile_index'])
        if current is None:
            blockers.append(part['id'] + ':profile_missing')
            continue
        bounds = list(primitive_bounds(analysis.profiles[current.profile_index]))
        if (bounds != part['bounds_mm'] or list(current.bend_indices) != part['bend_indices']
                or bool(current.text_frame) != part['text_frame'] or current.label != part['label']):
            blockers.append(part['id'] + ':geometry_or_identity_changed')
            continue
        if not part['included']:
            continue
        ledger = ParameterLedger.from_dict(part['ledger'])
        values = {key: row.value for key, row in ledger.parameters.items()}
        # The legacy writer requires radius and angle even for a flat base.
        # Do not manufacture arbitrary process values to satisfy that interface.
        required = ['radius', 'angle'] + (['k_factor'] if current.bend_indices else [])
        missing = ledger.blockers(required)
        if missing:
            blockers.extend(part['id'] + ':' + key + ':required_by_native_adapter' for key in missing)
            continue
        if values['hole_policy'] not in {'scale_all', 'preserve_circle_diameter'}:
            blockers.append(part['id'] + ':unsupported_hole_policy')
            continue
        quantity = int(values['quantity'])
        output_name = format_sheet_part_name(1, quantity, values['thickness'])
        entries.append({'id': part['id'], 'profile_index': current.profile_index,
            'label': current.label, 'quantity': quantity, 'parameters': values,
            'bounds_mm': bounds, 'bend_indices': list(current.bend_indices),
            'relative_output': part['id'] + '/' + output_name,
            'reviewed_job': asdict(replace(current, quantity=quantity,
                quantity_source=ledger.parameters['quantity'].source,
                thickness_mm=values['thickness'], thickness_source=ledger.parameters['thickness'].source)),
            'native_acceptance': 'unverified'})
    if file_hash(source) != manifest['source_sha256']:
        blockers.append('source_changed_during_preparation')
    return {**report, 'status': 'blocked' if blockers else 'ready_for_owned_execution_unverified',
        'blockers': sorted(set(blockers)), 'source': str(source),
        'source_sha256': manifest['source_sha256'], 'entries': [] if blockers else entries,
        'native_write_allowed': False, 'cad_executed': False}


def _write_receipt(folder, receipt):
    """Atomically update metadata inside this newly created task directory."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                                         prefix='.receipt-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(receipt, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, folder / 'execution.receipt.json')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def execute_reviewed_batch(manifest, *, expected_review_sha256, output_dir, source=None,
                           progress=None):
    """Execute only from the already proven exclusive STA; never launch here.

    expected_review_sha256 is the caller's explicit choice of reviewed content,
    not an authentication token. Transport authorization stays with the host.
    Every part gets a separate folder and a save/reopen observation. A session
    error stops the batch; retained files never count as engineering acceptance.
    """
    import sys
    from batch_export import SheetPartJob, export_all_sheet_parts
    from bend_allowance import resolve_bend_allowance_spec
    from cad_analyzer import analyze_cad_file
    from part_verification import verify_saved_part
    from sw_session import SessionOwnershipError, require_model_write
    if sys.platform != 'win32':
        raise RuntimeError('reviewed native execution requires Windows')
    if not isinstance(expected_review_sha256, str) or digest(manifest) != expected_review_sha256:
        raise ValueError('explicit current review SHA256 required')
    plan = prepare_execution(manifest, source=source)
    if plan['blockers']:
        raise ValueError('reviewed batch blocked: ' + ', '.join(plan['blockers']))
    lease = require_model_write()
    if not lease.verified_exclusive:
        raise SessionOwnershipError('reviewed batch requires a proven exclusive task instance')
    folder = Path(output_dir).resolve()
    if folder.exists():
        raise FileExistsError('reviewed batch output must be a new task directory')
    # Analysis happens once for execution; every writer receives this same
    # immutable baseline rather than a previous part's resized analysis.
    analysis = analyze_cad_file(plan['source'])
    if file_hash(plan['source']) != plan['source_sha256']:
        raise ValueError('source changed before batch execution')
    require_model_write(lease)
    folder.mkdir(parents=True, exist_ok=False)
    receipt = {'schema_version': 1, 'review_sha256': expected_review_sha256,
        'source_sha256': plan['source_sha256'], 'task_id': lease.task_id,
        'status': 'running', 'cad_executed': False, 'parts': [],
        'unattempted': [e['id'] for e in plan['entries']], 'production_approved': False,
        'solidworks_acceptance': 'unverified', 'engineering_acceptance': 'unverified'}
    _write_receipt(folder, receipt)
    try:
        for entry in plan['entries']:
            require_model_write(lease)
            if file_hash(plan['source']) != plan['source_sha256'] or digest(manifest) != expected_review_sha256:
                raise ValueError('source or review changed during execution')
            values = entry['parameters']
            part_folder = folder / entry['id']
            if part_folder.exists():
                raise FileExistsError('part task directory already exists')
            raw_job = dict(entry['reviewed_job'])
            raw_job['bend_indices'] = tuple(raw_job['bend_indices'])
            job = SheetPartJob(**raw_job)
            allowance = None
            if job.bend_indices:
                allowance, _ = resolve_bend_allowance_spec(thickness_mm=values['thickness'],
                    radius_mm=values['radius'], angle_degrees=values['angle'],
                    mode='k_factor', k_factor=values['k_factor'])
            record = {'id': entry['id'], 'status': 'running', 'cad_attempted': True,
                      'path': None, 'production_approved': False}
            receipt['parts'].append(record)
            receipt['unattempted'].remove(entry['id'])
            receipt['cad_executed'] = True
            _write_receipt(folder, receipt)
            results = export_all_sheet_parts(analysis, jobs=[job],
                thickness_mm=values['thickness'], radius_mm=values['radius'],
                angle_degrees=values['angle'], bend_allowance=allowance,
                output_dir=part_folder, uniform_scale=values['scale'],
                preserve_circle_holes=values['hole_policy'] == 'preserve_circle_diameter',
                progress=progress, skip_existing=False)
            if len(results) != 1 or not results[0].ok or results[0].status != 'passed':
                record['status'] = 'failed_or_degraded'
                if results:
                    record['error'] = results[0].error
                    record['path'] = str(results[0].path) if results[0].path else None
                raise RuntimeError('reviewed part did not complete; remaining writes stopped')
            artifact = Path(results[0].path).resolve(strict=True)
            if artifact != (folder / entry['relative_output']).resolve():
                raise RuntimeError('artifact path differs from reviewed execution plan')
            record.update(path=str(artifact), sha256=file_hash(artifact), status='saved_pending_reopen')
            _write_receipt(folder, receipt)
            require_model_write(lease)
            observation = verify_saved_part(artifact, expected_body_count=1)
            record.update(status='reopened_pending_engineering', reopen=observation)
            _write_receipt(folder, receipt)
        if file_hash(plan['source']) != plan['source_sha256']:
            raise ValueError('source changed by the end of the batch')
        receipt['status'] = 'generated_pending_engineering'
    except Exception as error:
        receipt.update(status='stopped', error={'type': type(error).__name__, 'message': str(error)})
        if receipt['parts'] and receipt['parts'][-1]['status'] == 'running':
            receipt['parts'][-1]['status'] = 'failed_or_unverified'
        # A writer can save a file and then fail COM/K readback before returning
        # its path. Inventory only this new task folder, never customer inputs.
        try:
            retained = []
            for artifact in folder.rglob('*'):
                if artifact.suffix.casefold() != '.sldprt' or not artifact.is_file():
                    continue
                if artifact.is_symlink() or not artifact.resolve().is_relative_to(folder):
                    continue
                retained.append({'path': artifact.relative_to(folder).as_posix(),
                                 'sha256': file_hash(artifact), 'acceptance': 'unverified'})
                if len(retained) >= 10000:
                    break
            receipt['retained_artifacts'] = retained
        except OSError as inventory_error:
            receipt['retained_inventory_error'] = str(inventory_error)
        _write_receipt(folder, receipt)
        raise
    _write_receipt(folder, receipt)
    return receipt
