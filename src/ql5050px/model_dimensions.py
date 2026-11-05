"""Pilot import of real model dimensions, never numeric text replacements.

SW API: InsertModelAnnotations3, GetFirstDisplayDimension5/GetNext5,
IDimension.GetType and IDisplayDimension.GetOverride. COM stays lazy.
"""
import math
from .native_machine import read_member


def _typed(value,interface):
    if value is not None and hasattr(value,'_oleobj_'):
        import solidworks_generator as sw
        return sw._as_interface(sw.ensure_solidworks_typelib(),value,interface)
    return value


def parameter_name(full_name):
    pieces=str(full_name).split('@')
    if len(pieces)<2 or not all(pieces[:2]):raise ValueError('native dimension identity unavailable')
    return '@'.join(pieces[:2])


def dimension_value(dimension):
    dimension=_typed(dimension,'IDimension')
    if dimension is None:raise RuntimeError('native model dimension missing')
    full_name=str(read_member(dimension,'FullName'))
    kind=int(read_member(dimension,'GetType'));value=float(read_member(dimension,'SystemValue'))
    if kind not in (0,1) or not math.isfinite(value):raise RuntimeError('unsupported/nonfinite native model dimension')
    return {'full_name':full_name,'parameter':parameter_name(full_name),'parameter_type':kind,
            'value_si':value,'unit_si':'m' if kind==0 else 'rad'}


def display_dimension_value(display):
    display=_typed(display,'IDisplayDimension')
    annotation=_typed(read_member(display,'GetAnnotation'),'IAnnotation')
    return {**dimension_value(display.GetDimension2(0)),
            'overridden':bool(read_member(display,'GetOverride')),
            'uses_document_units':bool(read_member(display,'GetUseDocUnits')),
            'visibility_state':int(read_member(annotation,'Visible'))}


def dimension_values_match(actual,expected):
    return (actual['full_name']==expected['full_name'] and actual['parameter_type']==expected['parameter_type']
        and actual['overridden']==expected['overridden']
        and actual['uses_document_units']==expected['uses_document_units']
        and actual['visibility_state']==expected['visibility_state']
        and math.isclose(actual['value_si'],expected['value_si'],rel_tol=0,abs_tol=1e-9))


def validate_required_parameters(names):
    if not isinstance(names,list) or not names or len(names)>128:
        raise ValueError('explicit bounded list of required model dimensions needed')
    if any(not isinstance(name,str) or parameter_name(name)!=name for name in names) or len(set(names))!=len(names):
        raise ValueError('required model dimensions must be unique Dn@Feature identities')
    return names


def insert_model_dimensions(driver,drawing,source,views,required):
    validate_required_parameters(required);driver.guard()
    expected=[];missing=[]
    for name in required:
        dimension=source.Parameter(name)
        if dimension is None:missing.append(name)
        else:expected.append(dimension_value(dimension))
    if missing:return {'expected':expected,'missing_source_parameters':missing,'attempted':False}
    from .com_selection import select_by_id
    drawing.ClearSelection2(True)
    if not select_by_id(drawing.Extension,str(read_member(views['front'],'GetName2')),'DRAWINGVIEW'):
        raise RuntimeError('model dimension target view selection failed')
    # Entire model=0, marked=32768, unmarked=524288. No duplicate dimensions,
    # hidden feature dimensions or handwritten numerical override.
    drawing.InsertModelAnnotations3(0,32768|524288,True,False,False,False)
    drawing.ClearSelection2(True)
    if not read_member(drawing,'EditRebuild3'):raise RuntimeError('imported dimensions rebuild failed')
    return {'expected':expected,'missing_source_parameters':[],'attempted':True}


def _display_records(views):
    """Include hidden dimensions so their persistent state can be verified."""
    for view_id,raw in views.items():
        view=_typed(raw,'IView');display=read_member(view,'GetFirstDisplayDimension5');seen=set()
        while display is not None:
            display=_typed(display,'IDisplayDimension')
            row=display_dimension_value(display)
            annotation=_typed(read_member(display,'GetAnnotation'),'IAnnotation')
            name=str(read_member(annotation,'GetName'))
            identity=(name,row['full_name'])
            if identity in seen or len(seen)>=512:raise RuntimeError('cyclic/oversized display dimension chain')
            seen.add(identity)
            yield {'view':view_id,'name':name,'annotation_type':int(read_member(annotation,'GetType')),
                   'model_dimension':row},display,annotation
            display=read_member(display,'GetNext5')


def collect_model_dimensions(views):
    """Evidence contains individually visible model dimensions only."""
    from .drawing_verification import annotation_evidence
    result=[]
    for record,display,_ in _display_records(views):
        if record['model_dimension']['visibility_state']!=1:continue
        evidence=annotation_evidence(display,'model_dimension',{'view':record['view'],
            'parameter':record['model_dimension']['parameter']})
        result.append({**evidence,'model_dimension':record['model_dimension']})
    return result


def duplicate_dimension_plan(records,preferences=None):
    """Only repeated presentations of the same full model identity can hide."""
    preferences={} if preferences is None else preferences
    if not isinstance(preferences,dict) or any(view not in {'front','top','right'} for view in preferences.values()):
        raise ValueError('dimension view preferences must select front/top/right')
    groups={}
    for index,row in enumerate(records):
        if row['model_dimension']['visibility_state']==1:
            groups.setdefault(row['model_dimension']['full_name'],[]).append(index)
    keep=[];hide=[];blocked=[]
    for full_name,indexes in groups.items():
        first=records[indexes[0]]['model_dimension']
        if any(not dimension_values_match(records[i]['model_dimension'],first)
               or records[i]['model_dimension']['overridden'] for i in indexes):
            blocked.append(full_name);keep.extend(indexes);continue
        preferred=preferences.get(first['parameter'])
        selected=next((i for i in indexes if records[i]['view']==preferred),indexes[0])
        keep.append(selected);hide.extend(i for i in indexes if i!=selected)
    return {'keep':keep,'hide':hide,'blocked_parameters':blocked}


def deduplicate_model_dimensions(driver,drawing,views,preferences=None):
    driver.guard();live=list(_display_records(views));records=[row for row,_,_ in live]
    plan=duplicate_dimension_plan(records,preferences);hidden=[];immediate_ok=True
    for index in plan['hide']:
        row,_,annotation=live[index];driver.guard()
        annotation.Visible=3  # swAnnotationHidden, not deleted and not half-hidden.
        state=int(read_member(annotation,'Visible'));immediate_ok=immediate_ok and state==3
        hidden.append({**row,'model_dimension':{**row['model_dimension'],'visibility_state':3}})
    if plan['hide']:
        read_member(drawing,'GraphicsRedraw2')
        if not read_member(drawing,'EditRebuild3'):raise RuntimeError('dimension visibility rebuild failed')
    return {'status':'applied' if immediate_ok and not plan['blocked_parameters'] else 'pending_deduplication',
            'kept_dimensions':len(plan['keep']),'hidden_dimensions':hidden,
            'blocked_parameters':plan['blocked_parameters'],'reopened_verified':False,'model_dimensions_deleted':False}


def verify_hidden_dimensions(views,proof):
    actual={(row['view'],row['name'],row['model_dimension']['full_name']):row
            for row,_,_ in _display_records(views)}
    # Some SW drawing view display-dimension chains omit hidden dimensions.
    # IAnnotation.GetNext3 explicitly includes hidden/suppressed annotations.
    wanted_by_view={}
    for row in proof['hidden_dimensions']:
        key=(row['view'],row['name'],row['model_dimension']['full_name'])
        if key not in actual:wanted_by_view.setdefault(row['view'],set()).add(row['name'])
    for view_id,names in wanted_by_view.items():
        view=_typed(views[view_id],'IView');annotation=read_member(view,'GetFirstAnnotation3');seen=[]
        while annotation is not None:
            annotation=_typed(annotation,'IAnnotation');name=str(read_member(annotation,'GetName'))
            # D1 can refer to multiple different features in the same view.
            # Cycle detection must compare native object identity, not names.
            if hasattr(annotation,'_oleobj_'):
                import pythoncom
                identity=annotation._oleobj_.QueryInterface(pythoncom.IID_IUnknown)
            else:identity=id(annotation)
            if any(identity==previous for previous in seen) or len(seen)>=4096:
                raise RuntimeError('cyclic/oversized hidden annotation chain')
            seen.append(identity)
            types={row.get('annotation_type') for row in proof['hidden_dimensions']
                   if row['view']==view_id and row['name']==name}
            if name in names and (None in types or int(read_member(annotation,'GetType')) in types):
                display=read_member(annotation,'GetSpecificAnnotation')
                row=display_dimension_value(display)
                actual[(view_id,name,row['full_name'])]={'view':view_id,'name':name,'model_dimension':row}
            annotation=read_member(annotation,'GetNext3')
    missing=[]
    for row in proof['hidden_dimensions']:
        key=(row['view'],row['name'],row['model_dimension']['full_name'])
        if key not in actual or not dimension_values_match(actual[key]['model_dimension'],row['model_dimension']):missing.append(key)
    return {**proof,'reopened_verified':not missing and proof['status']=='applied',
            'unverified_hidden_dimensions':[list(key) for key in missing],
            'hidden_lookup':'display_dimension_and_complete_annotation_chains'}


def dimension_coverage(source,imported):
    expected=source['expected'];missing=list(source['missing_source_parameters']);issues=[]
    for item in expected:
        matches=[row['model_dimension'] for row in imported if row['model_dimension']['parameter']==item['parameter']]
        if not matches:missing.append(item['parameter']);continue
        if any(row['full_name']!=item['full_name'] or row['parameter_type']!=item['parameter_type']
               or not math.isclose(row['value_si'],item['value_si'],rel_tol=0,abs_tol=1e-9)
               or row['overridden'] or not row['uses_document_units'] or row['visibility_state']!=1 for row in matches):
            issues.append({'parameter':item['parameter'],'issue':'value_identity_override_or_units_unverified'})
    return {'status':'verified' if expected and not missing and not issues else 'pending_dimensions',
            'source_parameters':expected,'missing_parameters':sorted(set(missing)),
            'issues':issues,'display_dimensions':len(imported),'reopened_verified':False,
            'manufacturing_approved':False}


def dimension_import_verified(data):
    """Recompute coverage from annotation rows, not just a stored status flag."""
    try:
        proof=data.get('model_dimension_import') or {}
        rows=[row for row in data.get('annotations',[]) if row['kind']=='model_dimension']
        if (not rows or not all(row.get('reopened') is True for row in rows)
                or proof.get('reopened_verified') is not True or proof.get('status')!='verified'
                or proof.get('display_dimensions')!=len(rows) or proof.get('missing_parameters') or proof.get('issues')):
            return False
        if data.get('requested',{}).get('deduplicate_model_dimensions'):
            dedup=data.get('dimension_deduplication') or {}
            if (dedup.get('status')!='applied' or dedup.get('reopened_verified') is not True
                    or dedup.get('kept_dimensions')!=len(rows)
                    or len({row['model_dimension']['full_name'] for row in rows})!=len(rows)):
                return False
        return dimension_coverage({'expected':proof['source_parameters'],'missing_source_parameters':[]},rows)['status']=='verified'
    except (KeyError,TypeError,ValueError):return False
