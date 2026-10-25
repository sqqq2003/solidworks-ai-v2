"""Layered mate/joint diagnostics around existing scalar DOF heuristic."""
from ql5050px.assembly import inspect_assembly
from .common import index, number, result, review_digest


def diagnose_assembly(request):
    components=request['components']; nodes=index(components)
    mates=request['mates']; index(mates)
    offline=inspect_assembly(components,mates,request.get('transmissions',[]))
    failures=[]; pending=['offline_DOF_is_not_constraint_Jacobian_rank']; strokes=[]
    for row in offline['issues']:
        if row['kind']=='invalid_reference': failures.append('invalid_mate_reference')
        else: pending.append('offline:'+row['kind'])
    for key,value in offline['estimated_dof'].items():
        # Existing scalar count is advisory; redundant constraints need native rank.
        if value!=0: pending.append('estimated_nonzero_DOF:'+key)
    seen=set()
    for mate in mates:
        signature=(tuple(sorted([mate['a'],mate['b']])),mate['type'],str(mate.get('reference','')))
        if signature in seen and not mate.get('suppressed'): pending.append('possible_redundant_mate:'+mate['id'])
        seen.add(signature)
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
    return result({'offline':offline,'travel_checks':strokes,'native_readback':native,
                   'native_evidence_independently_verified':False},issues=pending,failed=failures)
