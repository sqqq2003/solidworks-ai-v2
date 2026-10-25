"""Sourced design intent and dependency impact over existing planner output."""
from copy import deepcopy
import hashlib,json,math

PROTECTED={'interface','fixed','purchased'}
ROLES=PROTECTED|{'adjustable','unknown'}


def review_digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def finite(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite numeric dimension required')
    return float(value)


def changes_from_plan(plan):
    """Reuse roller-variant or drive-variant contracts; no second solver."""
    if 'changes' in plan:return deepcopy(plan['changes'])
    return [{**edit,'document':part.get('document'),'configuration':part.get('configuration')}
            for part in plan.get('component_modifications',[]) for edit in part['edits']]


def analyze_impact(plan,intentions):
    changes=changes_from_plan(plan);register=intentions.get('parameters',{})
    graph=intentions.get('dependency_graph',{})
    changed=[];preserved=[];risks=[];conflicts=[];pending=[];seen=set()
    if plan.get('status') in {'pending_mapping','conflict','failed'}:
        pending.append({'reason':'upstream_plan_not_ready','status':plan['status']})
    if not changes:pending.append({'reason':'no_explicit_change_plan'})
    for edit in changes:
        name=edit['parameter']
        if name in seen:pending.append({'parameter':name,'reason':'ambiguous_repeated_parameter; use scoped identifiers'})
        seen.add(name);intent=register.get(name,{})
        role=intent.get('role','unknown')
        if role not in ROLES:raise ValueError('unknown design role: '+role)
        before=finite(edit['before_mm'] if 'before_mm' in edit else edit['before'])
        after=finite(edit['after_mm'] if 'after_mm' in edit else edit['after'])
        unit=edit.get('unit','mm' if 'before_mm' in edit else None)
        confirmed=intent.get('review_status')=='confirmed' and bool(intent.get('source'))
        row={**edit,'before':before,'after':after,'unit':unit,'role':role,'intent_source':intent.get('source')}
        if unit is None or intent.get('unit')!=unit:pending.append({'parameter':name,'reason':'missing_or_conflicting_units'})
        if not confirmed or role=='unknown':pending.append({'parameter':name,'reason':'design_intent_needs_confirmation'})
        different=not math.isclose(before,after,rel_tol=0,abs_tol=1e-9)
        if different:
            changed.append(row)
            if role in PROTECTED:conflicts.append({'parameter':name,'reason':'protected_design_interface','role':role})
            if role=='adjustable':
                bounds=intent.get('allowed_range')
                if bounds is None:pending.append({'parameter':name,'reason':'missing_allowed_range'})
                else:
                    if len(bounds)!=2:raise ValueError('allowed range needs two endpoints')
                    lo,hi=map(finite,bounds)
                    if lo>hi:raise ValueError('reversed allowed range')
                    if not lo<=after<=hi:conflicts.append({'parameter':name,'reason':'outside_reviewed_range'})
        else:preserved.append(row)
    # Protected intent outside the edit list still becomes a mandatory readback.
    protected_checks=[]
    for name,intent in register.items():
        if intent.get('role') in PROTECTED:
            protected_checks.append({'parameter':name,'role':intent['role'],'expected':'unchanged','source':intent.get('source')})
            if intent.get('review_status')!='confirmed' or not intent.get('source'):
                pending.append({'parameter':name,'reason':'protected_intent_needs_confirmation'})
    active=set();done=set()
    def visit(name):
        if name in active:raise ValueError('cyclic design dependency: '+name)
        if name in done:return
        active.add(name)
        for dep in graph.get(name,[]):visit(dep)
        active.remove(name);done.add(name)
    for name in graph:visit(name)
    affected={row['parameter'] for row in changed}
    while True:
        new={name for name,deps in graph.items() if set(deps)&affected}-affected
        if not new:break
        affected|=new
    for name in sorted(affected):
        if name not in register:pending.append({'parameter':name,'reason':'affected_item_not_mapped'})
        if name not in seen:risks.append({'parameter':name,'reason':'dependent_item_requires_explicit_recompute_or_native_readback'})
    report={'schema_version':1,'plan_sha256':review_digest(plan),'intent_sha256':review_digest(intentions),
        'changes':changed,'unchanged_edits':preserved,'protected_readbacks':protected_checks,
        'affected_parameters':sorted(affected),'affected_features':deepcopy(plan.get('affected_features',[])),
        'affected_mates':deepcopy(plan.get('affected_mates',[])),
        'conflicts':conflicts,'pending_confirmation':pending,'risks':risks,
        'status':'failed' if conflicts else 'review_required',
        'review_ready':bool(changes) and not conflicts and not pending,
        'native_write_allowed':False,'cad_executed':False,
        'recognition_scope':'reviewed intent over existing plans; feature-name hints never auto-confirm intent',
        'required_validation':['dimensions','protected_interfaces','feature_tree','rebuild','references','save_reopen','process_exit']}
    report['review_sha256']=review_digest(report);return report


def record_approval(report,*,reviewer,review_sha256):
    payload=deepcopy(report);declared=payload.pop('review_sha256',None)
    if not isinstance(reviewer,str) or not reviewer.strip():raise ValueError('named reviewer required')
    if declared!=review_sha256 or review_digest(payload)!=review_sha256:raise ValueError('stale impact review digest')
    if not report.get('review_ready') or report.get('conflicts'):raise ValueError('unresolved impact review cannot be approved')
    return {'reviewer':reviewer,'review_sha256':review_sha256,'plan_sha256':report['plan_sha256'],
        'intent_sha256':report['intent_sha256'],'status':'review_recorded',
        'native_write_allowed':False,'scope':'review record only; host ownership/input hash checks still required'}
