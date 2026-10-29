"""P0 CAD -> native sheet metal plan and recoverable artifact transaction.

Legacy geometry and generation remain the implementation; mock success is never
native acceptance. Parameters and bend direction require explicit confirmation.
"""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Protocol

logger = logging.getLogger(__name__)

from run_recovery import (STAGE_ORDER, RunLock, quarantine_orphan_staging,
                          read_checkpoints, validate_checkpoint_chain,
                          write_checkpoint, write_crash_package)
from bend_allowance import resolve_bend_allowance_spec
from profile_selection import contained_hole_indices, outermost_containing_profile_index
from profile_sanitize import contour_self_intersects, sanitize_closed_profile
from solidworks_generator import (profile_bend_indices, minimal_relief_width_mm,
                                 minimal_relief_depth_past_centerline_mm)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def analysis_hash(analysis):
    return digest(asdict(analysis))


def code_hash():
    root = Path(__file__).parent
    return digest({name: file_hash(root/name) for name in (
        'sheet_metal_pipeline.py', 'sheet_metal_windows.py', 'cad_analyzer.py',
        'solidworks_generator.py', 'profile_sanitize.py', 'profile_selection.py', 'profile_edit.py',
        'bend_allowance.py', 'sw_session.py', 'sw_owned_launch.py',
        'bridge_wiring.py', 'owned_document_lifetime.py',
        'sw_compat/__init__.py', 'sw_compat/dispatch.py', 'sw_compat/typelib.py')})


def build_plan(analysis, *, profile_index=0, thickness_mm=None, radius_mm=None,
               angle_degrees=None, k_factor=None, flip_direction=None,
               relief_bend_indices=(), units_confirmed=False, bends_confirmed=False):
    if not 0 <= profile_index < len(analysis.profiles):
        raise ValueError('selected profile does not exist')
    if outermost_containing_profile_index(analysis.profiles, profile_index) != profile_index:
        raise ValueError('selected contour is an internal hole; select outer contour explicitly')
    profile = analysis.profiles[profile_index]
    if not profile.closed or profile.is_bend or contour_self_intersects(profile.points):
        raise ValueError('outer profile must be closed and non-self-intersecting')
    sanitize_closed_profile(profile, min_edge_mm=0.05)
    holes = contained_hole_indices(analysis.profiles, profile_index)
    for index in holes:
        if contour_self_intersects(analysis.profiles[index].points):
            raise ValueError('self-intersecting internal contour')
        if contained_hole_indices(analysis.profiles, index):
            raise ValueError('nested islands require explicit topology review')
    bends = profile_bend_indices(profile, analysis.bend_lines, [analysis.profiles[i] for i in holes])
    relief = tuple(dict.fromkeys(relief_bend_indices))
    if any(type(i) is not int or i not in bends for i in relief):
        raise ValueError('relief indices must belong to selected bend lines')
    pending = []
    if bends and not bends_confirmed:
        pending.append('bend_line_classification')
    for index in bends:
        bend = analysis.bend_lines[index]
        if len(bend.points) < 2 or math.dist(bend.points[0], bend.points[-1]) <= 1e-8:
            raise ValueError('degenerate bend line')
        if any(segment.center is not None for segment in bend.curve_segments):
            pending.append('curved_bend_' + str(index))
    params = dict(thickness_mm=thickness_mm, radius_mm=radius_mm,
                  angle_degrees=angle_degrees, k_factor=k_factor, flip_direction=flip_direction)
    for key in ('thickness_mm', 'radius_mm', 'angle_degrees', 'k_factor'):
        value = params[key]
        if value is None:
            pending.append(key)
        elif type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError(key + ' must be finite numeric')
    for key in ('thickness_mm', 'radius_mm'):
        if params[key] is not None and params[key] <= 0:
            raise ValueError(key + ' must be positive')
    if angle_degrees is not None and not 0 < angle_degrees < 180:
        raise ValueError('bend angle must be between 0 and 180')
    if k_factor is not None and not 0 <= k_factor <= 1:
        raise ValueError('K factor must be between 0 and 1')
    if flip_direction is None:
        pending.append('bend_direction')
    elif type(flip_direction) is not bool:
        raise ValueError('bend direction must be boolean')
    if '未指定' in analysis.units_name and not units_confirmed:
        pending.append('source_units')
    allowance = None
    if all(params[k] is not None for k in ('thickness_mm','radius_mm','angle_degrees','k_factor')):
        if radius_mm <= 0:
            raise ValueError('native generator requires positive radius')
        spec, preview = resolve_bend_allowance_spec(thickness_mm=thickness_mm, radius_mm=radius_mm,
            angle_degrees=angle_degrees, mode='k_factor', k_factor=k_factor)
        allowance = {'spec': asdict(spec), 'preview': asdict(preview)}
    relief_rule = None if thickness_mm is None or radius_mm is None else {
        'width_mm': minimal_relief_width_mm(thickness_mm),
        'depth_past_centerline_mm': minimal_relief_depth_past_centerline_mm(thickness_mm, radius_mm),
        'source': 'existing_generator_rule_not_measured', 'selected_bends': list(relief)}
    plan = {'schema_version': 1, 'source': str(analysis.path),
            'source_sha256': file_hash(analysis.path), 'analysis_sha256': analysis_hash(analysis),
            'code_sha256': code_hash(), 'units': 'mm', 'source_units': analysis.units_name,
            'profile_index': profile_index, 'hole_indices': list(holes), 'bend_indices': list(bends),
            'relief_bend_indices': list(relief), 'bend_classification_confirmed': bool(bends_confirmed),
            'parameters': params,
            'parameter_source': 'explicit_operator_inputs', 'bend_allowance': allowance,
            'relief_rule': relief_rule, 'pending': pending,
            'status': 'pending' if pending else 'ready_for_windows',
            'feature_plan': ['closed_profile_and_holes', 'native_base_flange',
                *(['native_sketched_bends'] if bends else []), 'rebuild', 'save',
                'reopen_and_inspect_editable_features', 'flat_pattern', 'export_dxf'],
            'sw_live_verified': False}
    plan['plan_id'] = digest(plan)
    return plan


class SheetMetalPort(Protocol):
    simulated: bool
    def generate(self, analysis, plan: dict, part: Path) -> dict: ...
    def reopen_inspect(self, part: Path) -> dict: ...
    def export_flat(self, part: Path, dxf: Path) -> None: ...
    def abort(self, stage: Path) -> None: ...


def validate_native(plan, evidence):
    if not evidence.get('reopened') or not evidence.get('rebuilt'):
        raise RuntimeError('reopen/rebuild not verified')
    types = set(evidence.get('feature_types', []))
    if not {'SheetMetal', 'FlatPattern', 'SMBaseFlange'} <= types or not evidence.get('editable'):
        raise RuntimeError('native editable sheet-metal feature tree not verified')
    if plan['bend_indices'] and (evidence.get('bend_feature_count', 0) < 1 or
            (len(plan['bend_indices']) > 1 and evidence.get('completed_bend_count') != len(plan['bend_indices']))):
        raise RuntimeError('native bend features incomplete; reference sketch is not an automatic bend')
    for key in ('thickness_mm', 'radius_mm', 'k_factor'):
        actual = evidence.get(key)
        if type(actual) not in (float, int) or not math.isfinite(actual) or not math.isclose(actual, plan['parameters'][key], abs_tol=1e-6):
            raise RuntimeError(key + ' native readback mismatch or missing')


def run_plan(analysis, plan, output_dir, port: SheetMetalPort, bridge=None):
    # Bridge wiring (Issue #25, next batch): ``bridge`` is an optional
    # BridgeWiring (src/bridge_wiring.py) wrapping a bridge client. None
    # preserves the exact pre-wiring behavior: no bridge evidence blocks
    # are recorded at all. A supplied wiring never upgrades a run: bridge
    # evidence says which channel answered, never "native SolidWorks ran".
    expected = dict(plan)
    plan_id = expected.pop('plan_id')
    if digest(expected) != plan_id or plan['code_sha256'] != code_hash():
        raise ValueError('modified or stale plan; regenerate')
    if plan['source_sha256'] != file_hash(analysis.path) or plan['analysis_sha256'] != analysis_hash(analysis):
        raise ValueError('source or analyzed geometry changed; regenerate plan')
    if plan['pending']:
        return {'status': 'pending', 'pending': plan['pending'], 'sw_live_verified': False}
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    label = ('simulation-' if port.simulated else 'native-') + plan_id
    destination = root / label
    # Issue #19: crash-safe publish lock. A live owner's lock is never stolen;
    # a stale lock (dead owner pid or expired heartbeat) is archived, not deleted.
    run_lock = RunLock(root, label, plan_id=plan_id)
    lock_status = run_lock.acquire()
    if lock_status != 'acquired':
        logger.info('recovered stale publish lock for plan %s', plan_id)
    stage = None
    generated = None
    evidence = None
    part = None
    ckpt_dir = None
    checkpoints = {}
    resume_stage = None
    try:
        # A completed destination always wins; any staging left behind is
        # stale by definition, so quarantine everything in that case.
        def _resumable(candidate):
            if (candidate/'RECOVERY_REQUIRED.json').is_file():
                raise RuntimeError('native failed staging requires operator review; use a new output root after session review')
            found, _ckpts = validate_checkpoint_chain(
                candidate / 'ckpt', plan_id=plan_id,
                code_sha256=plan['code_sha256'], base_dir=candidate)
            return found is not None
        resumable, quarantined = quarantine_orphan_staging(
            root, label, is_resumable=(lambda candidate: False) if destination.exists()
            else _resumable)
        if quarantined:
            logger.info('quarantined orphan staging: %s', [str(q) for q in quarantined])
        if destination.exists():
            manifest = json.loads((destination/'result.json').read_text())
            if manifest['plan_id'] != plan_id or manifest['simulated_only'] != port.simulated:
                raise RuntimeError('existing artifact manifest does not match')
            expected_status = 'simulated_pass' if port.simulated else 'native_features_verified'
            if manifest.get('status') != expected_status or manifest.get('sw_live_verified') != (not port.simulated):
                raise RuntimeError('existing result status inconsistent with backend')
            if not port.simulated:
                validate_native(plan, manifest['reopen'])
            required = {'part.trace.json', 'flat.trace.json'} if port.simulated else {'part.SLDPRT', 'flat.DXF'}
            if set(manifest['artifact_sha256']) != required:
                raise RuntimeError('incomplete artifact manifest')
            for name, checksum in manifest['artifact_sha256'].items():
                if Path(name).name != name or file_hash(destination/name) != checksum:
                    raise RuntimeError('artifact changed; refusing stale resume')
            return {**manifest, 'resumed': True, 'output_dir': str(destination)}
        if resumable:
            # Adopt the staging directory with the longest verified chain.
            best = None
            for candidate in resumable:
                found, ckpts = validate_checkpoint_chain(
                    candidate / 'ckpt', plan_id=plan_id,
                    code_sha256=plan['code_sha256'], base_dir=candidate)
                if found is not None and (best is None
                        or STAGE_ORDER.index(found) > STAGE_ORDER.index(best[1])):
                    best = (candidate, found, ckpts)
            stage, resume_stage, checkpoints = best
            ckpt_dir = stage / 'ckpt'
            if resume_stage in ('S1', 'S2', 'S3'):
                generated = checkpoints['S1']['evidence'].get('generation')
            if resume_stage in ('S2', 'S3'):
                evidence = checkpoints['S2']['evidence'].get('reopen')
            logger.info('resuming plan %s from checkpoint %s in %s',
                        plan_id, resume_stage, stage)
        else:
            stage = Path(tempfile.mkdtemp(prefix='.'+label+'-', dir=root))
            ckpt_dir = stage / 'ckpt'
            ckpt_dir.mkdir()
        part = stage / ('part.trace.json' if port.simulated else 'part.SLDPRT')
        flat = stage / ('flat.trace.json' if port.simulated else 'flat.DXF')
        if resume_stage is None:
            # S0: plan locked. Later stages are skipped only when this
            # fingerprint still matches, so a changed plan/code can never
            # silently resume past a stage it did not produce.
            write_checkpoint(ckpt_dir, 'S0', plan_id=plan_id,
                             code_sha256=plan['code_sha256'], products=(),
                             evidence={'status': 'plan_locked'})
            checkpoints = read_checkpoints(ckpt_dir)
        run_lock.heartbeat()
        if resume_stage in (None, 'S0'):
            # S1: generation. When a bridge wiring is supplied, the bridge
            # build method runs first; any bridge failure (unavailable,
            # unsupported by an older client, method error, timeout) falls
            # back to port.generate for this stage, recorded with
            # executed_via + fallback_reason. A bridge build that reports
            # success must have written the part file to the staging path
            # (contract: the bridge writes only to the given work-copy
            # path); a missing product is a hard failure, not a fallback.
            if bridge is not None:
                s1_bridge = bridge.build_evidence(
                    plan_id=plan_id, title=part.name, part_path=part,
                    parameters=plan['parameters'],
                    bend_count=len(plan['bend_indices']))
                if s1_bridge.get('executed_via') == 'bridge':
                    generated = s1_bridge['result']
                    if not part.is_file() or part.stat().st_size == 0:
                        raise RuntimeError(
                            'bridge build reported success but part file missing')
                else:
                    generated = port.generate(analysis, plan, part)
            else:
                generated = port.generate(analysis, plan, part)
            if not port.simulated and plan['bend_indices'] and (not generated.get('auto_bent') or generated.get('auto_bend_failed_count', 0)):
                raise RuntimeError('automatic bending incomplete; manual/reference fallback rejected')
            s1_evidence = {'generation': generated}
            if bridge is not None:
                s1_evidence['bridge'] = s1_bridge
            write_checkpoint(ckpt_dir, 'S1', plan_id=plan_id,
                             code_sha256=plan['code_sha256'],
                             products=[{'name': part.name, 'sha256': file_hash(part)}],
                             evidence=s1_evidence)
            if not port.simulated:
                from sw_session import current_lease
                live_lease = current_lease()
                if live_lease is not None:
                    live_lease.generation_saved = True
            checkpoints = read_checkpoints(ckpt_dir)
        run_lock.heartbeat()
        if resume_stage in (None, 'S0', 'S1'):
            # S2: fresh reopen + native feature readback. When a bridge
            # wiring is supplied, the bridge reopen method runs first and
            # its readback is validated exactly like a port readback; any
            # bridge failure falls back to port.reopen_inspect for this
            # stage, recorded with executed_via + fallback_reason.
            if bridge is not None:
                s2_bridge = bridge.reopen_evidence(
                    plan_id=plan_id, title=part.name, part_path=part)
                if s2_bridge.get('executed_via') == 'bridge':
                    evidence = s2_bridge['readback']
                else:
                    evidence = port.reopen_inspect(part)
            else:
                evidence = port.reopen_inspect(part)
            if not port.simulated:
                validate_native(plan, evidence)
            s2_evidence = {'reopen': evidence}
            if bridge is not None:
                s2_evidence['bridge'] = s2_bridge
            write_checkpoint(ckpt_dir, 'S2', plan_id=plan_id,
                             code_sha256=plan['code_sha256'],
                             products=[{'name': part.name, 'sha256': file_hash(part)}],
                             evidence=s2_evidence)
            checkpoints = read_checkpoints(ckpt_dir)
        run_lock.heartbeat()
        if resume_stage in (None, 'S0', 'S1', 'S2'):
            # S3: flat-pattern export.
            port.export_flat(part, flat)
            if not port.simulated:
                import ezdxf
                drawing = ezdxf.readfile(flat)
                if not list(drawing.modelspace()):
                    raise RuntimeError('flat DXF contains no geometry')
            for product in (part, flat):
                if not product.is_file() or product.stat().st_size == 0:
                    raise RuntimeError('missing or empty product: ' + product.name)
            write_checkpoint(ckpt_dir, 'S3', plan_id=plan_id,
                             code_sha256=plan['code_sha256'],
                             products=[{'name': p.name, 'sha256': file_hash(p)}
                                       for p in (part, flat)],
                             evidence={'export': 'flat_exported'})
            checkpoints = read_checkpoints(ckpt_dir)
        run_lock.heartbeat()
        result = {'status': 'simulated_pass' if port.simulated else 'native_features_verified',
                  'plan_id': plan_id, 'simulated_only': port.simulated,
                  'sw_live_verified': not port.simulated, 'mechanical_acceptance': 'unverified',
                  'generation': generated, 'reopen': evidence,
                  'artifact_sha256': {p.name: file_hash(p) for p in (part, flat)}}
        (stage/'result.json').write_text(json.dumps(result, indent=2, default=str, allow_nan=False)+'\n')
        os.rename(stage, destination)
        stage = None
        # Keep the published artifact dir to result + products only (the
        # dry-run contract asserts every entry there is JSON): relocate the
        # checkpoint evidence to a hidden sibling directory instead of
        # leaving it inside the destination.
        ckpt_dir = root / ('.' + label + '.ckpt')
        try:
            os.rename(destination / 'ckpt', ckpt_dir)
        except OSError:
            logger.warning('could not relocate checkpoint dir; leaving it in %s',
                           destination)
            ckpt_dir = destination / 'ckpt'
        # S4: acceptance landed. S5: run_plan teardown. The SolidWorks
        # process exit code is NOT recorded here; the session owner
        # (owned_solidworks evidence) owns it, and it stays
        # pending_windows_validation until Gork runs it.
        products = [{'name': name, 'sha256': checksum}
                    for name, checksum in result['artifact_sha256'].items()]
        write_checkpoint(ckpt_dir, 'S4', plan_id=plan_id,
                         code_sha256=plan['code_sha256'], products=products,
                         evidence={'status': result['status']})
        s5_evidence = {'teardown': 'run_plan_complete_lock_released_by_finally',
                       'process_exit_code': 'recorded_by_session_owner_not_here',
                       'pending_windows_validation': True}
        if bridge is not None:
            # Bridge wiring: the bridge 5-step teardown report (steps +
            # exit code) is recorded into ckpt-S5. A bridge teardown
            # failure does NOT unpublish the already-landed artifact: it
            # is recorded here plus a crash package, and acceptance
            # readers must check ckpt-S5 before claiming "full-process
            # stable". Plain bridge unavailability is fallback, not a
            # failure, and gets no crash package.
            bridge_evidence, bridge_error = bridge.teardown_evidence()
            s5_evidence['bridge'] = bridge_evidence
            if bridge_error is not None:
                logger.warning('bridge teardown failed for plan %s: %s', plan_id, bridge_error)
                try:
                    crash_file = write_crash_package(
                        root, plan_id=plan_id, error=bridge_error,
                        checkpoints=read_checkpoints(ckpt_dir), products=products)
                    s5_evidence['bridge_teardown_crash_package'] = str(crash_file)
                except Exception:
                    logger.warning('could not write S5 bridge crash package', exc_info=True)
        write_checkpoint(ckpt_dir, 'S5', plan_id=plan_id,
                         code_sha256=plan['code_sha256'], products=products,
                         evidence=s5_evidence)
        return {**result, 'resumed': resume_stage is not None, 'output_dir': str(destination)}
    except Exception as exc:
        from part_verification import (
            disconnect_after_saved_product,
            partial_rebind_after_save,
            rebind_failure_after_save,
            saved_generation_after_disconnect,
        )
        from sw_session import normalize_com_disconnect
        reported = normalize_com_disconnect(exc) or exc
        keep_disconnect = disconnect_after_saved_product(reported, part)
        keep_rebind = (not keep_disconnect) and rebind_failure_after_save(exc, part)
        if keep_disconnect or keep_rebind:
            # SaveAs3 already wrote the part. A later ActiveDoc
            # MEMBERNOTFOUND or COM drop must not delete it or report
            # generation as null. ExitApp stays unused.
            if generated is None and part is not None:
                generated = {
                    "path": Path(part).name,
                    "file_on_disk": True,
                    "saved_before_rebind": True,
                }
            kept = (
                saved_generation_after_disconnect(generated, reported)
                if keep_disconnect
                else partial_rebind_after_save(generated, exc)
            )
            crash_file = None
            if ckpt_dir is not None and Path(ckpt_dir).is_dir():
                try:
                    products = [{'name': p.name, 'size': p.stat().st_size}
                                for p in Path(stage).iterdir() if p.is_file()] \
                        if stage is not None and Path(stage).is_dir() else []
                    crash_file = write_crash_package(
                        root, plan_id=plan_id, error=exc,
                        checkpoints=read_checkpoints(ckpt_dir), products=products)
                except Exception:
                    crash_file = None
            kept.update({
                'plan_id': plan_id,
                'diagnostic_stage': str(stage) if stage is not None and Path(stage).exists() else None,
            })
            if crash_file is not None:
                kept['crash_package'] = str(crash_file)
            diagnostic = root / ('failure-' + uuid.uuid4().hex + '.json')
            diagnostic.write_text(json.dumps(kept, ensure_ascii=False, indent=2, default=str)+'\n')
            return {**kept, 'diagnostic_file': str(diagnostic)}
        recovery = 'not_needed'
        crash_file = None
        if ckpt_dir is not None and Path(ckpt_dir).is_dir():
            try:
                products = [{'name': p.name, 'size': p.stat().st_size}
                            for p in Path(stage).iterdir() if p.is_file()] \
                    if stage is not None and Path(stage).is_dir() else []
                crash_file = write_crash_package(
                    root, plan_id=plan_id, error=exc,
                    checkpoints=read_checkpoints(ckpt_dir), products=products)
            except Exception:
                crash_file = None
        if stage is not None:
            try:
                port.abort(stage)
                if port.simulated:
                    shutil.rmtree(stage)
                    recovery = 'staging_removed'
                else:
                    from run_recovery import atomic_write_json
                    atomic_write_json(Path(stage)/'RECOVERY_REQUIRED.json',{'plan_id':plan_id,'reason':str(exc),'native_acceptance':'pending_windows_validation'})
                    recovery = 'native_staging_preserved_review_required'
            except Exception as rollback:
                recovery = 'recovery_required: ' + str(rollback)
                if not port.simulated and Path(stage).is_dir():
                    from run_recovery import atomic_write_json
                    atomic_write_json(Path(stage)/'RECOVERY_REQUIRED.json',{'plan_id':plan_id,'reason':str(exc),'cleanup_error':str(rollback)})
        failure = {'status': 'failed', 'error': str(exc), 'error_kind': type(exc).__name__,
                   'bend_group_attempts': list(getattr(exc, 'bend_group_attempts', ())),
                   'failed_bend_indices': list(getattr(exc, 'bend_indices', ())),
                   'completed_bend_count': getattr(exc, 'completed_bend_count', None),
                   'recovery': recovery,
                   'plan_id': plan_id, 'sw_live_verified': False, 'generation': generated,
                   'diagnostic_stage': str(stage) if stage and stage.exists() else None}
        if crash_file is not None:
            failure['crash_package'] = str(crash_file)
        diagnostic = root / ('failure-' + uuid.uuid4().hex + '.json')
        diagnostic.write_text(json.dumps(failure, ensure_ascii=False, indent=2)+'\n')
        return {**failure, 'diagnostic_file': str(diagnostic)}
    finally:
        run_lock.release()


class MockSheetMetalPort:
    simulated = True
    def generate(self, analysis, plan, part):
        part.write_text(json.dumps({'mock': True, 'plan_id': plan['plan_id']}))
        return {'auto_bent': False, 'cad_executed': False}
    def reopen_inspect(self, part):
        return {'mock': True, 'reopened': False, 'editable': False}
    def export_flat(self, part, dxf):
        dxf.write_text(json.dumps({'mock': True, 'cad_executed': False}))
    def abort(self, stage):
        pass


def diagnose_k_change(*, thickness_mm, radius_mm, angle_degrees, old_k, new_k,
                      geometry_basis, old_flat_mm=None, new_flat_mm=None):
    """K changes need a dimension basis. A fixed DXF blank need not change length.

    This is a formula diagnostic, never proof of a SolidWorks run. Folded legs
    refer to fixed outside legs at their virtual sharp intersection.
    """
    from bend_allowance import compute_bend_allowance
    old = compute_bend_allowance(thickness_mm, radius_mm, angle_degrees, old_k)
    new = compute_bend_allowance(thickness_mm, radius_mm, angle_degrees, new_k)
    if geometry_basis not in {'fixed_blank', 'fixed_outside_legs'}:
        raise ValueError('unknown dimensional basis; do not guess K effect')
    expected = 0.0 if geometry_basis == 'fixed_blank' else new.bend_allowance_mm - old.bend_allowance_mm
    observed = None
    if old_flat_mm is not None and new_flat_mm is not None:
        if any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in (old_flat_mm, new_flat_mm)):
            raise ValueError('flat lengths must be finite positive measurements')
        observed = new_flat_mm - old_flat_mm
    return {'geometry_basis': geometry_basis, 'expected_single_bend_delta_mm': expected,
            'observed_delta_mm': observed, 'native_k_readback': 'required',
            'status': 'pending_measurement' if observed is None else (
                'consistent_with_formula' if math.isclose(observed, expected, abs_tol=1e-5) else 'mismatch'),
            'sw_live_verified': False}


