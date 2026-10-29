"""Single-dimension rehearsal packages and read-only evidence consistency checks."""
from collections import Counter
import hashlib
import json
from math import isclose
from pathlib import Path
from .assembly_builder import finite
from .integrated import run_integrated

STEPS = ('source_isolation','dimension_before','dimension_after_reopen','rebuild',
         'save_reopen','mates','interference','travel','drawing','bom')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): value.update(block)
    return value.hexdigest()


def prepare_case(request):
    result = run_integrated(request)
    plan = result['machine_plan']['drive_plan']
    bridge = result['windows_tasks']['decision_bridge']
    blockers = []
    qa = request.get('acceptance',{})
    if qa.get('source_kind') != 'oem': blockers.append('real OEM source not declared; fixture only')
    for field in ('mapping_review_source','mate_inventory_review_source','source_inventory_review_source'):
        if not qa.get(field): blockers.append(field+' required')
    if bridge['pending_mapping']: blockers.append('decision bridge has unresolved actions')
    if any(row['action'] != 'resize' for row in bridge['converted']):
        blockers.append('first rehearsal permits resize only')
    if len(bridge['converted']) != 1:
        blockers.append('exactly one approved decision conversion required')
    edits = [(c,e) for c in plan['component_modifications'] for e in c['edits']]
    if len(edits) != 1: blockers.append('exactly one native dimension edit required')
    if plan['status'] != 'ready_for_native' or plan['pending_mapping'] or plan['conflicts']:
        blockers.append('drive plan unresolved or conflicted')
    if plan['affected_mates']: blockers.append('first rehearsal cannot rewrite mates')
    expected = None
    if len(edits) == 1:
        component,edit = edits[0]
        if len(bridge['converted']) == 1 and edit['parameter'] != bridge['converted'][0].get('drive_parameter'):
            blockers.append('native edit is not the approved decision conversion')
        before,after = finite(edit['before']),finite(edit['after'])
        if (edit['unit'] != 'mm' or edit['role'] != 'dimension' or
                not isinstance(edit['target'],str) or component['component_kind'] != 'editable'):
            blockers.append('only an editable length dimension in mm is supported')
        if before <= 0 or after <= 0 or before == after:
            blockers.append('positive distinct before/after dimensions required')
        expected = {'document':component['document'],'configuration':component['configuration'],
                    'dimension':edit['target'],'before_mm':before,'after_mm':after}
    sources = qa.get('source_files',[])
    if not isinstance(sources,list) or not all(isinstance(p,str) and p for p in sources):
        raise ValueError('acceptance.source_files must be a list of paths')
    required = [plan.get('source_assembly')] + [c.get('document') for c,e in edits]
    # Path/configuration binding comes from the reviewed request; originals are hashed only.
    paths = list(dict.fromkeys(p for p in required+sources if p))
    manifest = {}
    for path in paths:
        try:
            if not Path(path).is_file() or Path(path).stat().st_size == 0:
                raise OSError('source missing or empty')
            manifest[path] = file_digest(path)
        except OSError:
            blockers.append('source unavailable: '+path)
    if not sources: blockers.append('complete reviewed source_files inventory required')
    if any(p not in sources for p in required if p):
        blockers.append('source_files must include assembly and edited document')
    case = {'schema_version':1,'scope':'single_dimension_rehearsal','request':request,
            'drive_plan':plan,'expected':expected,'source_sha256':manifest,
            'blockers':blockers,'status':'blocked' if blockers else 'preflight_ready',
            'unresolved_whole_machine_items':len(result['pending_mapping']),
            'required_steps':list(STEPS),'native_write_allowed':False,
            'mechanical_acceptance':'unverified'}
    case['case_id'] = digest(case)
    return case


def evidence_template(case):
    return {'schema_version':1,'case_id':case['case_id'],'simulated_only':None,
            'operator':None,'observed_at_utc':None,'source_revision':None,
            'session':{'ownership':None,'attached_existing':None},
            'checks':[{'step':step,'status':'not_run','artifacts':[],
                       **({'value_mm':None,'configuration':None,'dimension':None}
                          if step.startswith('dimension_') else {})} for step in STEPS]}


def audit_case(case, evidence, evidence_root):
    """Validate submitted records/bytes; does not independently witness native CAD."""
    issues = []
    payload = dict(case)
    identity = payload.pop('case_id',None)
    if not identity or digest(payload) != identity or evidence.get('case_id') != identity:
        issues.append('case identity mismatch')
    if case.get('status') != 'preflight_ready' or case.get('blockers'):
        issues.append('case preflight blocked')
    if evidence.get('simulated_only') is not False: issues.append('native evidence not declared')
    for field in ('operator','observed_at_utc','source_revision'):
        if not evidence.get(field): issues.append(field+' missing')
    session = evidence.get('session',{})
    if session.get('ownership') != 'spawned_pid_and_live_handle' or session.get('attached_existing') is not False:
        issues.append('owned session evidence missing')
    for path,sha in case.get('source_sha256',{}).items():
        try:
            if file_digest(path) != sha: issues.append('original changed: '+path)
        except OSError: issues.append('original unavailable: '+path)
    root = Path(evidence_root).resolve()
    checks = evidence.get('checks',[])
    counts = Counter(row.get('step') for row in checks)
    if set(counts) != set(STEPS) or any(n != 1 for n in counts.values()):
        issues.append('missing, duplicate or unknown evidence steps')
    for row in checks:
        step = row.get('step')
        if row.get('status') != 'passed': issues.append(str(step)+': not passed')
        artifacts = row.get('artifacts',[])
        if not artifacts: issues.append(str(step)+': evidence files missing')
        for item in artifacts:
            relative = Path(item['path'])
            path = (root/relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(root):
                issues.append(str(step)+': artifact outside evidence directory')
                continue
            try:
                if not path.is_file() or path.stat().st_size == 0 or file_digest(path) != item.get('sha256'):
                    issues.append(str(step)+': evidence file missing/empty/changed')
            except OSError: issues.append(str(step)+': evidence unreadable')
        if step in ('dimension_before','dimension_after_reopen'):
            expected = case.get('expected') or {}
            try:
                value = finite(row.get('value_mm'))
                target = expected['before_mm' if step == 'dimension_before' else 'after_mm']
                if not isclose(value,finite(target),rel_tol=1e-9,abs_tol=1e-5):
                    issues.append(step+': dimension mismatch')
                if row.get('configuration') != expected['configuration'] or row.get('dimension') != expected['dimension']:
                    issues.append(step+': target/configuration mismatch')
            except (ValueError,TypeError,KeyError): issues.append(step+': finite dimension readback missing')
    counts = Counter(row.get('status','not_run') for row in checks)
    return {'status':'evidence_consistent' if not issues else 'review_required','case_id':identity,
            'counts':dict(counts),'issues':issues,'mechanical_acceptance':'unverified',
            'production_release':False,'cad_executed':False,
            'note':'Checks submitted records and bytes only; native authenticity and engineering release require independent review.'}
