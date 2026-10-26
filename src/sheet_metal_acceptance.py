"""Read-only consistency checks for native evidence; never runs or accepts mechanics."""
import hashlib
from pathlib import Path
from sheet_metal_pipeline import validate_native, digest


def audit_report(report):
    issues=[]
    plan=report.get('plan',{})
    result=report.get('execution',{})
    session=report.get('session',{})
    if result.get('status')!='native_features_verified' or result.get('simulated_only') is not False:
        issues.append('native_result_missing_or_simulated')
    expected=dict(plan)
    plan_id=expected.pop('plan_id',None)
    if not plan_id or digest(expected)!=plan_id or result.get('plan_id')!=plan_id:
        issues.append('plan_identity_mismatch')
    if session.get('ownership')!='spawned_pid_and_live_handle' or session.get('attached_existing') is not False:
        issues.append('owned_session_evidence_missing')
    if session.get('cleanup_error') or type(session.get('cleanup_exit_code')) is not int or session.get('cleanup_exit_code') != 0:
        issues.append('clean_process_exit_unverified')
    generation=result.get('generation') or {}
    count=len(plan.get('bend_indices',()))
    if count and (generation.get('auto_bent') is not True or generation.get('bend_count')!=count
                  or generation.get('auto_bend_abandoned') or generation.get('auto_bend_failed_count',0)):
        issues.append('incomplete_native_bends')
    try:
        validate_native(plan,result.get('reopen',{}))
    except (ValueError,TypeError,KeyError,RuntimeError) as error:
        issues.append('native_readback: '+str(error))
    checksums=result.get('artifact_sha256') or {}
    if set(checksums)!={'part.SLDPRT','flat.DXF'}:
        issues.append('required_artifacts_missing')
    folder=result.get('output_dir')
    if not folder:
        issues.append('artifact_directory_missing')
    else:
        root=Path(folder).resolve()
        for name in ('part.SLDPRT','flat.DXF'):
            product=(root/name).resolve()
            if not product.is_relative_to(root):
                issues.append('artifact_outside_output: '+name)
                continue
            try:
                data=product.read_bytes()
                if not data or hashlib.sha256(data).hexdigest()!=checksums.get(name):
                    issues.append('artifact_empty_or_changed: '+name)
            except OSError:
                issues.append('artifact_unreadable: '+name)
    return dict(status='evidence_consistent' if not issues else 'review_required',
                issues=issues,mechanical_acceptance='unverified',cad_executed=False,
                note='Checks submitted records and bytes; does not independently prove live CAD or manufacturing acceptance.')
