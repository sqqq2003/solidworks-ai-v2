"""Layered mate/joint diagnostics around existing scalar DOF heuristic."""
from ql5050px.assembly import inspect_assembly
from .common import index, number, result, review_digest
from .mate_rank import GEOMETRIC_TYPES, analyse_constraints

SCALAR_ONLY_ISSUES = {'dof_mismatch', 'possible_redundancy'}


def _constraint_rank(request, components, mates, nodes):
    active=[m for m in mates if not m.get('suppressed') and m['a'] in nodes and m['b'] in nodes and m['a']!=m['b']]
    if not any('geometry' in m for m in active): return None, []
    unsupported=[m['id'] for m in active if m['type'] not in GEOMETRIC_TYPES]
    missing=[m['id'] for m in active if m['type']!='fixed' and 'geometry' not in m]
    if unsupported: return None, ['constraint_rank_unsupported_mates:'+','.join(unsupported)]
    if missing: return None, ['constraint_rank_geometry_missing:'+','.join(missing)]
    report=analyse_constraints(components, active,
                               linear_tolerance_mm=request.get('linear_tolerance_mm', 0.01),
                               angular_tolerance_deg=request.get('angular_tolerance_deg', 0.01))
    return report, []


def diagnose_assembly(request):
    components=request['components']; nodes=index(components)
    mates=request['mates']; index(mates)
    offline=inspect_assembly(components,mates,request.get('transmissions',[]))
    rank,rank_pending=_constraint_rank(request,components,mates,nodes)
    failures=[]; pending=list(rank_pending); strokes=[]
    if rank is None: pending.insert(0,'offline_DOF_is_not_constraint_Jacobian_rank')
    for row in offline['issues']:
        if row['kind']=='invalid_reference': failures.append('invalid_mate_reference')
        elif rank is None or row['kind'] not in SCALAR_ONLY_ISSUES: pending.append('offline:'+row['kind'])
    if rank is None:
        for key,value in offline['estimated_dof'].items():
            # Existing scalar count is advisory; redundant constraints need native rank.
            if value!=0: pending.append('estimated_nonzero_DOF:'+key)
        seen=set()
        for mate in mates:
            signature=(tuple(sorted([mate['a'],mate['b']])),mate['type'],str(mate.get('reference','')))
            if signature in seen and not mate.get('suppressed'): pending.append('possible_redundant_mate:'+mate['id'])
            seen.add(signature)
    else:
        pending.extend(rank['issues']); failures.extend(rank['failures'])
    for joint in request.get('joints',[]):
        if joint['component'] not in nodes: failures.append('invalid_joint_reference:'+joint['id']); continue
        if joint.get('unit') not in {'mm','deg'} or not joint.get('source'): raise ValueError('joint unit/source required')
        lo,hi,pos=map(number,(joint['minimum'],joint['maximum'],joint['position']))
        if lo>hi: raise ValueError('invalid travel limits')
        ok=lo<=pos<=hi; strokes.append({'id':joint['id'],'within_travel':ok})
        if not ok: failures.append('travel_outside_limits:'+joint['id'])
    native=request.get('native_readback')
    if native:
        if native.get('assembly_sha256')!=review_digest({'components':components,'mates':mates}):
            failures.append('stale_native_readback')
        if native.get('scope')!='windows_solidworks' or not native.get('source'):
            pending.append('native_readback_provenance_missing')
        for key in ('mate_errors','invalid_references'):
            if native.get(key): failures.append('native_'+key)
        if any(native.get(k) is not True for k in ('rebuild_ok','reopened','motion_checked','interference_checked')):
            pending.append('native_checks_incomplete')
    else: pending.append('native_readback_not_run')
    return result({'offline':offline,'constraint_rank':rank,'travel_checks':strokes,'native_readback':native,
                   'native_evidence_independently_verified':False},issues=pending,failed=failures)
