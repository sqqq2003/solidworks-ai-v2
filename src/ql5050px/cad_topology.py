"""Conservative loop containment and dimensional evidence, reusing panel geometry."""
from .panel import polygon,area,edges,intersects,inside


def analyze_loops(entities):
    loops=[];uncertain=[]
    for e in entities:
        if e['type']=='polyline' and e.get('closed'):
            try:points=polygon(e['points'])
            except ValueError as exc:
                uncertain.append({'entity':e['id'],'reason':str(exc)});continue
            loops.append({'id':e['id'],'points':points,'area_mm2':abs(area(points))})
        elif e['type']=='circle':
            uncertain.append({'entity':e['id'],'reason':'circle retained as analytic hole candidate; not polygonized'})
    invalid=set()
    for i,a in enumerate(loops):
        for b in loops[i+1:]:
            if any(intersects(p,q,r,s) for p,q in edges(a['points']) for r,s in edges(b['points'])):
                invalid.update((a['id'],b['id']))
                uncertain.append({'entities':[a['id'],b['id']],'reason':'touching/intersecting contours; no inferred containment'})
    for a in loops:
        parents=[b for b in loops if b['id']!=a['id'] and b['id'] not in invalid and a['id'] not in invalid and inside(a['points'][0],b['points'])]
        parent=min(parents,key=lambda p:p['area_mm2']) if parents else None
        a['parent']=parent['id'] if parent else None
        a['containment_depth']=len(parents)
        a['role']='uncertain' if a['id'] in invalid else ('hole' if len(parents)%2 else 'outer_or_island')
    return {'loops':loops,'uncertainties':uncertain,'manufacturing_approved':False}


def dimension_relations(entities,tolerance_mm=0.01):
    if tolerance_mm<=0:raise ValueError('positive geometry comparison tolerance required')
    indexed={e['id']:e for e in entities};reports=[]
    for e in entities:
        if e['type']!='dimension':continue
        refs=e.get('references',[])
        missing=[r for r in refs if r not in indexed]
        reports.append({'dimension':e['id'],'references':refs,'value':e.get('value'),
            'unit':e.get('unit'),'source':e.get('source'),'missing_references':missing,
            'status':'pending_confirmation' if missing or not e.get('confirmed') else 'confirmed_input',
            'geometry_verified':False})
    return reports
