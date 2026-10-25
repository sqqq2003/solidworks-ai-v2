"""Overall length includes both shaft projections, never just barrel length."""
from copy import deepcopy
import hashlib,json,math
from sw_api.mapping import load_mappings

CORE=('overall_length','barrel_length','left_projection','right_projection')


def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite numeric mm value required')
    return float(value)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def plan_variant(request,measurements=None):
    if request.get('units')!='mm':raise ValueError('explicit mm units required')
    target=number(request.get('target_overall_mm',800))
    if target<=0:raise ValueError('positive total length required')
    rows=load_mappings(request.get('mappings',{'schema_version':1,'parameters':[]}))
    mapped={row.parameter:row for row in rows};values={};pending=[]
    for name,row in mapped.items():
        if row.unit!='mm':raise ValueError('roller dimension mappings must use mm')
        source=(measurements or {}).get(name,request.get('measurements',{}).get(name))
        if isinstance(source,dict):
            if source.get('confirmed') is not True or not source.get('source'):source=None
            else:source=source.get('value')
        if source is not None:values[name]=number(source)
        if row.status!='confirmed':pending.append({'parameter':name,'field':'native_mapping'})
    protected=request.get('protected_parameters',[])
    if not protected or 'shaft_diameter' not in protected:pending.append({'field':'protected_parameters_including_shaft_diameter'})
    for name in (*CORE,*protected):
        if name not in mapped or name not in values:pending.append({'parameter':name,'field':'mapping_and_measured_value'})
    if request.get('interface_inventory_status')!='confirmed' or not request.get('interface_inventory_source'):pending.append({'field':'shoulder_bearing_drive_interface_inventory'})
    if request.get('dependency_inventory_status')!='confirmed' or not request.get('dependency_inventory_source'):pending.append({'field':'shaft_and_mate_dependency_inventory'})
    if not request.get('source_document') or not request.get('configuration'):pending.append({'field':'source_document/configuration'})
    if request.get('axis') not in ('x','y','z'):pending.append({'field':'mapped_roller_axis'})
    changes=[];resolved=dict(values)
    if all(name in values for name in CORE):
        if min(values[n] for n in CORE)<=0:raise ValueError('positive measured roller lengths required')
        if not math.isclose(values['overall_length'],values['barrel_length']+values['left_projection']+values['right_projection'],abs_tol=.01,rel_tol=0):
            raise ValueError('measured overall is not barrel plus both shaft projections')
        barrel=target-values['left_projection']-values['right_projection']
        if barrel<=0:raise ValueError('target cannot contain both preserved shaft projections')
        resolved.update(overall_length=target,barrel_length=barrel)
        edits={'barrel_length':barrel}
        remaining=list(request.get('dependencies',[]));seen=set()
        while remaining:
            progress=False
            for rule in remaining[:]:
                name=rule['parameter'];deps=rule['depends_on']
                if name in seen or name=='barrel_length':raise ValueError('duplicate derived parameter')
                if any(d not in resolved or any(r['parameter']==d for r in remaining) for d in deps):continue
                value=sum(resolved[d] for d in deps)+number(rule.get('offset_mm',0))
                edits[name]=resolved[name]=value;seen.add(name);remaining.remove(rule);progress=True
            if not progress:raise ValueError('cyclic or unresolved roller dependency')
        for name,after in edits.items():
            if name in {'left_projection','right_projection'}:raise ValueError('shaft projections must be preserved')
            if name in protected:raise ValueError('protected interface cannot be edited: '+name)
            row=mapped.get(name)
            if row is None or name not in values:
                pending.append({'parameter':name,'field':'derived_dimension_mapping/readback'});continue
            if row.component_kind!='editable':raise ValueError('fixed/purchased dimensions cannot be stretched')
            if row.allowed_range is None:pending.append({'parameter':name,'field':'allowed_range'});continue
            if not row.allowed_range[0]<=after<=row.allowed_range[1]:raise ValueError(name+' outside mapped range')
            changes.append({'parameter':name,'before_mm':values[name],'after_mm':after,'dimension':row.dimension,'feature':row.feature,
                            'document':row.document,'configuration':row.configuration})
    result={'schema_version':1,'units':'mm','target_overall_mm':target,'length_definition':'barrel + left_projection + right_projection',
        'before_mm':values,'resolved_mm':resolved,'changes':changes,'protected_parameters':protected,
        'affected_features':sorted({c['feature'] for c in changes}),
        'affected_mates':deepcopy(request.get('affected_mates',[])),'pending_mapping':pending,
        'status':'pending_mapping' if pending else 'ready_for_native','cad_executed':False,
        'native_acceptance':'pending_windows_validation','request':deepcopy(request)}
    result['plan_sha256']=digest(result);return result
