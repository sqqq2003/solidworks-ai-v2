"""Four-state evidence assessment, distinct from CAD/manufacturing approval."""
import hashlib,math,re
from pathlib import Path,PurePosixPath,PureWindowsPath

PROFILES={
 'roller':{'checks':('owned_session','dimensions','protected_interfaces','feature_tree','rebuild','references','save_reopen','process_exit'),'artifacts':('model',)},
 'sheet':{'checks':('owned_session','dimensions','feature_tree','rebuild','references','save_reopen','sheet_parameters','flat_pattern','process_exit'),'artifacts':('model','flat_dxf')},
 'machine':{'checks':('owned_session','dimensions','protected_interfaces','feature_tree','rebuild','references','save_reopen','mates','interference','motion','manufacturing','process_exit'),'artifacts':('model','drawing','bom')}}


def evaluate_acceptance(record,*,artifact_root=None):
    profile=PROFILES[record['profile']];run_id=record.get('run_id');revision=record.get('source_revision')
    pending=[];failures=[];warnings=[];checks=[];artifacts=[]
    if not isinstance(revision,str) or not re.fullmatch('[a-f0-9]{40}',revision):pending.append('missing_pinned_source_revision')
    if not isinstance(run_id,str) or not run_id.strip():pending.append('missing_run_id')
    raw=record.get('checks',[]);by_id={}
    for row in raw:
        if row['id'] in by_id:raise ValueError('duplicate acceptance check: '+row['id'])
        by_id[row['id']]=row
    required=set(profile['checks'])
    for name in sorted(required|set(by_id)):
        row=by_id.get(name,{});status=row.get('status','not_run');critical=name in required
        if status not in {'passed','failed','degraded','review_required','not_run','not_applicable'}:raise ValueError('unknown check status')
        evidence=row.get('evidence',{})
        applicable=not (status=='not_applicable' and row.get('applicability_reviewed') is True and row.get('applicability_source') and name in {'mates','interference','motion'})
        verified=bool(evidence.get('source')) and evidence.get('run_id')==run_id and evidence.get('source_revision')==revision and bool(run_id) and bool(revision)
        issue=None
        if not applicable:outcome='not_applicable'
        elif status=='failed':
            outcome='failed';issue='reported_check_failure';(failures if critical else warnings).append(name+':'+issue)
        elif status=='passed' and row.get('execution')=='native' and verified:
            outcome='passed'
            if name in {'dimensions','protected_interfaces','sheet_parameters'}:
                comparisons=evidence.get('comparisons')
                if not isinstance(comparisons,list) or not comparisons:
                    outcome='review_required';issue='missing_numeric_readback';pending.append(name+':'+issue)
                else:
                    for comparison in comparisons:
                        values=[comparison.get(k) for k in ('expected','actual','tolerance')]
                        valid=all(type(v) in (int,float) and math.isfinite(v) for v in values)
                        if not valid or values[2]<0 or comparison.get('unit') not in {'mm','m','deg','ratio','count'} or not comparison.get('name'):
                            outcome='review_required';issue='invalid_numeric_readback';pending.append(name+':'+issue)
                        elif abs(values[0]-values[1])>values[2]:
                            outcome='failed';issue='numeric_readback_mismatch';failures.append(name+':'+issue)
            if name=='owned_session' and (evidence.get('ownership')!='spawned_pid_and_live_handle' or evidence.get('attached_existing') is not False):
                outcome='review_required';issue='owned_session_proof_missing';pending.append(name+':'+issue)
            if name=='process_exit' and (type(evidence.get('exit_code')) is not int or evidence['exit_code']!=0):
                outcome='failed' if type(evidence.get('exit_code')) is int else 'review_required'
                issue='nonzero_or_unobserved_exit'
                (failures if outcome=='failed' else pending).append(name+':'+issue)
        else:
            outcome='review_required';issue='missing_unverified_or_offline_evidence'
            (pending if critical else warnings).append(name+':'+issue)
        checks.append({'id':name,'required':critical,'status':outcome,'reason':issue})
    root=Path(artifact_root).resolve() if artifact_root is not None else None
    roles=set()
    for row in record.get('artifacts',[]):
        name=row.get('name');role=row.get('role');roles.add(role)
        if not isinstance(name,str) or not name or PurePosixPath(name).root or PureWindowsPath(name).root or PureWindowsPath(name).drive or '\\' in name or '..' in PurePosixPath(name).parts:
            failures.append('external_artifact');continue
        if root is None:pending.append('artifact_root_not_provided');continue
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():failures.append('missing_or_external_artifact:'+name);continue
        data=path.read_bytes();actual=hashlib.sha256(data).hexdigest()
        if not data or actual!=row.get('sha256'):failures.append('artifact_empty_or_changed:'+name)
        artifacts.append({'name':name,'role':role,'sha256':actual,'matches':bool(data) and actual==row.get('sha256')})
    for role in profile['artifacts']:
        if role not in roles:pending.append('missing_artifact_role:'+role)
    status='failed' if failures else 'review_required' if pending else 'degraded' if warnings else 'passed'
    return {'schema_version':1,'status':status,'profile':record['profile'],'run_id':run_id,'source_revision':revision,
        'checks':checks,'artifact_checks':artifacts,'failures':failures,'pending':pending,'warnings':warnings,
        'acceptance_scope':'submitted evidence identity and artifact integrity, not independent native execution',
        'cad_executed':False,'manufacturing_approved':False,'automatic_repair_executed':False}
