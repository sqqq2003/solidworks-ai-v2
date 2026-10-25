"""Instantiate explicit versioned machine/module templates without string eval."""
from copy import deepcopy
from .calculations import number
from design_review.impact import review_digest


def instantiate(template,values):
    if not all(template.get(k) for k in ('id','revision','source')):raise ValueError('versioned sourced template required')
    parameters=template['parameters'];unknown=set(values)-set(parameters)
    if unknown:raise ValueError('unknown template parameter: '+str(sorted(unknown)))
    pending=[];resolved={}
    for key,spec in parameters.items():
        if key not in values:pending.append(key);continue
        row=values[key]
        if row.get('unit')!=spec['unit'] or not row.get('source'):raise ValueError('template value unit/source required')
        value=number(row['value'])
        if spec.get('protected') and value!=number(spec['baseline']):raise ValueError('protected template parameter changed: '+key)
        bounds=spec.get('allowed_range')
        if bounds is not None and not number(bounds[0])<=value<=number(bounds[1]):raise ValueError('template parameter outside range: '+key)
        resolved[key]=value
    payload=deepcopy(template['payload'])
    supplied_paths=set()
    for binding in template.get('bindings',[]):
        if binding['parameter'] not in resolved:continue
        keys=binding['path']
        if not isinstance(keys,list) or not keys:raise ValueError('structured template binding path required')
        target=payload
        for key in keys[:-1]:target=target[key]
        if isinstance(target,dict) and keys[-1] not in target:raise ValueError('template target not declared')
        target[keys[-1]]=resolved[binding['parameter']]
        supplied_paths.add(tuple(keys))
    def manufacturing_inputs(value,path=()):
        if isinstance(value,dict):
            for key,child in value.items():
                nested=path+(key,)
                if key in {'thickness_mm','radius_mm','angle_degrees','k_factor'} and nested not in supplied_paths:
                    value[key]=None;pending.append('per_job:'+str(list(nested)))
                else:manufacturing_inputs(child,nested)
        elif isinstance(value,list):
            for index,child in enumerate(value):manufacturing_inputs(child,path+(index,))
    manufacturing_inputs(payload)
    return {'template_id':template['id'],'revision':template['revision'],'template_sha256':review_digest(template),
        'payload':payload,'resolved':resolved,'pending_confirmation':pending,'status':'pending_mapping' if pending else 'review_required',
        'native_write_allowed':False,'cad_executed':False}


def module_diff(previous,current):
    old=previous.get('modules',{});new=current.get('modules',{});rows=[]
    for key in sorted(set(old)|set(new)):
        if old.get(key)!=new.get(key):rows.append({'module':key,'before':old.get(key),'after':new.get(key)})
    return {'changes':rows,'requires_regeneration':[r['module'] for r in rows],'native_write_allowed':False}
