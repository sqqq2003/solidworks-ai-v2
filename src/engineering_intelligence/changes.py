"""Artifact dependency and design change reports, reusing canonical review digests."""
from collections import deque
from .common import index, result, review_digest


def track_changes(request):
    before, after = index(request['before']), index(request['after'])
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    children = {k: [] for k in after}; failures=[]
    for key, node in after.items():
        for dep in node.get('depends_on', []):
            if dep not in after: failures.append('invalid_reference:'+key+'->'+dep)
            else: children[dep].append(key)
    indegree={k:len(set(d for d in r.get('depends_on',[]) if d in after)) for k,r in after.items()}
    queue=deque(k for k,n in indegree.items() if not n); order=[]
    while queue:
        key=queue.popleft(); order.append(key)
        for child in set(children[key]):
            indegree[child]-=1
            if not indegree[child]: queue.append(child)
    if len(order)!=len(after): failures.append('dependency_cycle')
    # Use both graphs so deleting/changing a reference still invalidates consumers.
    all_children={k:set(v) for k,v in children.items()}
    for key,node in before.items():
        for dep in node.get('depends_on',[]): all_children.setdefault(dep,set()).add(key)
    affected=set(changed); queue=deque(changed)
    while queue:
        for child in all_children.get(queue.popleft(),()):
            if child not in affected: affected.add(child); queue.append(child)
    pending=[]
    for key in affected:
        node=after.get(key,before.get(key,{}))
        if node.get('kind')=='purchased': pending.append('supplier_review_required:'+key)
        if not node.get('source') or not node.get('revision'): pending.append('missing_provenance:'+key)
    return result({'baseline_sha256':review_digest(request['before']), 'proposed_sha256':review_digest(request['after']),
                   'changed':changed,'removed':sorted(before.keys()-after.keys()),'affected':sorted(affected),
                   'regenerate':[k for k in order if k in affected and after[k].get('kind') in {'part','assembly','drawing','bom','dxf'}],
                   'diffs':[{'id':k,'before':before.get(k),'after':after.get(k)} for k in changed],
                   'rollback':{'mode':'restore_baseline_to_new_directory','baseline':request['before'],'overwrite_original':False},
                   'native_write_allowed':False},issues=pending,failed=failures)


def change_report(request):
    impact=track_changes(request)
    evidence=request.get('evidence',[]); pending=[]
    import re
    for row in evidence:
        if not row.get('source') or not re.fullmatch('[0-9a-f]{64}',row.get('sha256','')):
            pending.append('missing_evidence_hash_or_source')
    if not evidence: pending.append('no_validation_evidence')
    if request.get('validation_status') not in {'passed','degraded','failed','review_required'}:
        pending.append('missing_validation_status')
    return result({'impact':impact,'parameter_differences':request.get('parameter_differences',[]),
                   'evidence':evidence,'validation_status':request.get('validation_status','not_run'),
                   'report_sha256':review_digest(request),'rollback':impact['rollback'],
                   'evidence_scope':'declared hashes only; use test_handoff_audit for physical file verification'},
                  issues=impact['issues']+pending,failed=impact['failures']+(['validation_failed'] if request.get('validation_status')=='failed' else []))
