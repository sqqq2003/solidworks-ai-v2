"""Evidence-ranked candidate mappings. Never auto-confirm OEM targets."""
import re
ALIASES={'length':('length','长度','总长'),'width':('width','宽度'),'height':('height','高度'),
 'conveyor_height':('passline','输送高度'),'center_distance':('center','中心距'),
 'stroke':('stroke','行程'),'left_drive_x':('left','左安装'),'right_drive_x':('right','右安装')}


def map_parameters(database, pending):
    names = [p if isinstance(p,str) else p.get('parameter',p.get('field','unknown')) for p in pending]
    graph={d.get('name'):d.get('depends_on',[]) for doc in database['documents'].values() for d in doc.get('dimensions',[]) if d.get('name')}
    cycles=[]
    def visit(name,trail):
        if name in trail:
            cycles.append(trail+[name]);return
        for dependency in graph.get(name,[]): visit(dependency,trail+[name])
    for name in graph: visit(name,[])
    reports=[]
    for parameter in dict.fromkeys(names):
        words = ALIASES.get(parameter,()) + (parameter,)
        candidates=[]
        for key,doc in database['documents'].items():
            for dim in doc.get('dimensions',[]):
                text=(dim.get('name','')+' '+dim.get('feature','')).casefold()
                hits=[w for w in words if w.casefold() in text]
                if not hits: continue
                protected=doc.get('component_kind') in {'fixed','purchased'}
                measured=dim.get('value') is not None and dim.get('unit') in {'mm','m','deg'}
                candidates.append({'document_id':key,'model_path':doc['path'],'configuration':doc['configuration'],
                    'feature':dim.get('feature'),'dimension':dim.get('name'),'units':dim.get('unit'),
                    'measured_value':dim.get('value') if measured else None,
                    'source':dim.get('source','snapshot'),'confidence':min(.85,.45+.1*len(hits)),
                    'evidence':hits,'protected':protected,'review_status':'review_required',
                    'equation_evidence':doc.get('equations',[]),'mate_evidence':doc.get('mates',[])})
        reports.append({'parameter':parameter,'candidates':sorted(candidates,key=lambda c:-c['confidence']),
                        'status':'review_required' if candidates else 'pending_mapping',
                        'ambiguous':len(candidates)>1,'auto_write_allowed':False})
    return {'schema_version':1,'mappings':reports,'auto_write_allowed':False,'dependency_cycles':cycles}


def confirmed_targets(report, approvals):
    """Separate explicit approval boundary; reject ambiguous or unmeasured targets."""
    if report.get('dependency_cycles'): raise ValueError('cyclic dimensions require manual review')
    targets=[]
    for approval in approvals:
        row=next(r for r in report['mappings'] if r['parameter']==approval['parameter'])
        matches=[c for c in row['candidates'] if c['document_id']==approval['document_id'] and c['dimension']==approval['dimension']]
        if len(matches)!=1 or approval.get('reviewed') is not True or not approval.get('source'):
            raise ValueError('unique sourced manual approval required')
        item=matches[0]
        if item['protected'] or item['measured_value'] is None: raise ValueError('protected/unmeasured target rejected')
        targets.append({**item,'parameter':row['parameter'],'review_status':'confirmed','approval_source':approval['source']})
    return targets
