"""A01 offline assembly checks reusing QL graph and sampled AABB checks."""
import math
from ..ql5050px.assembly import inspect_assembly, sample_motion, interference


def _number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('finite numeric motion input required')
    return value


def preflight_assembly(payload):
    if not isinstance(payload,dict) or payload.get('schema_version') != 1 or payload.get('units') != 'mm':
        raise ValueError('assembly schema_version 1 and mm required')
    components=payload['components']
    if not isinstance(components,list) or not components:
        raise ValueError('nonempty components required')
    ids=[c['id'] for c in components]
    if any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError('unique nonempty component ids required')
    graph=inspect_assembly(components,payload.get('mates',[]),payload.get('transmissions',[]))
    times=payload.get('times_s',[])
    if not isinstance(times,list) or len(times)>1000:
        raise ValueError('at most 1000 time samples allowed')
    times=[_number(t) for t in times]
    if any(t<0 for t in times) or times!=sorted(set(times)):
        raise ValueError('times must be nonnegative and strictly increasing')
    trajectories={}
    for row in payload.get('linear_motion',[]):
        name=row['component']
        if name not in ids or name in trajectories:
            raise ValueError('unknown or duplicate moving component')
        if next(c for c in components if c['id']==name).get('fixed'):
            raise ValueError('fixed component cannot have a trajectory')
        speed=tuple(_number(x) for x in row['velocity_mm_s'])
        if len(speed)!=3:
            raise ValueError('xyz velocity required')
        trajectories[name]=lambda t,speed=speed:tuple(t*x for x in speed)
    clearance=_number(payload.get('clearance_mm',0))
    graph['interference']=interference(components,clearance)
    motion=sample_motion(components,trajectories,times,clearance)
    issues=list(graph['issues'])
    if graph['interference']['missing_geometry']:
        issues.append({'kind':'missing_geometry','components':graph['interference']['missing_geometry']})
    if graph['interference']['candidates']:
        issues.append({'kind':'static_interference_candidates'})
    if not times:
        issues.append({'kind':'motion_samples_missing'})
    for frame in motion['frames']:
        if frame['candidates']:
            issues.append({'kind':'sampled_interference_candidates','time_s':frame['time_s']})
    return dict(status='review_required' if issues else 'offline_consistent',
                assembly=graph,motion=motion,issues=issues,cad_executed=False,
                mates_solved=False,mechanical_acceptance='unverified',
                note='Heuristic DOF and sampled translation AABBs only; no native mate solve or continuous collision proof.')
