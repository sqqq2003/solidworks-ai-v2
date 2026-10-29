"""Reviewable part decisions using existing assembly/drive planning contracts."""
from .mechanical_selection import positive


def decide(database, mappings, target, rules):
    for axis in ('length','width','height'): positive(target[axis])
    mapped={r['parameter']:r for r in mappings['mappings']}
    order,done,active=[],set(),set()
    def visit(key):
        if key in active: raise ValueError('decision dependency cycle')
        if key in done:return
        active.add(key)
        for dep in rules.get(key,{}).get('depends_on',[]):
            if dep not in database['documents']:raise ValueError('unknown decision dependency')
            visit(dep)
        active.remove(key);done.add(key);order.append(key)
    for key in database['documents']:visit(key)
    actions,pending=[],[]
    for key in order:
        doc=database['documents'][key]
        rule=rules.get(key,{})
        kind=doc.get('component_kind','unconfirmed')
        changes=[]
        for parameter,new_value in rule.get('targets',{}).items():
            report=mapped.get(parameter,{})
            candidate=report.get('candidates',[])
            matching=[c for c in candidate if c['document_id']==key and c.get('review_status')=='confirmed']
            if len(matching)!=1 or matching[0].get('review_status')!='confirmed':
                pending.append({'document':key,'parameter':parameter,'reason':'explicit confirmed mapping required'})
                continue
            c=matching[0]
            changes.append({'parameter':parameter,'before':c['measured_value'],'after':new_value,
                            'dimension':c['dimension'],'unit':c['units']})
        requested=rule.get('action','manual_review')
        if requested not in {'resize','translate','replace','regenerate','keep','manual_review'}: raise ValueError('unknown decision action')
        protected=kind in {'fixed','purchased','standard'} or doc.get('protected_interface')
        if protected and requested not in {'keep','manual_review'}:
            if not (requested=='translate' and rule.get('allow_reposition') is True): requested='manual_review'
        if requested=='resize' and (not changes or kind!='editable'): requested='manual_review'
        if requested in {'replace','regenerate'} and not rule.get('approved_specification'): requested='manual_review'
        if requested=='translate' and not rule.get('translation_mm'): requested='manual_review'
        actions.append({'document':key,'path':doc['path'],'action':requested,'changes':changes,
            'translation_mm':rule.get('translation_mm'),'affected_mates':doc.get('mates',[]),
            'risks':['interference and travel require native verification'],
            'rollback':{'restore_dimensions':[{**c,'after':c['before']} for c in changes],
                        'discard_only_isolated_work_copy':True},'native_write_allowed':False})
    return {'target_mm':target,'actions':actions,'pending_mapping':pending,
            'status':'review_required','propagation_order':order,'automatic_scaling':False,'native_write_allowed':False}
