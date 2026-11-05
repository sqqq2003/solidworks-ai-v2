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
    return {**dimension_value(display.GetDimension2(0)),
            'overridden':bool(read_member(display,'GetOverride')),
            'uses_document_units':bool(read_member(display,'GetUseDocUnits'))}


def dimension_values_match(actual,expected):
    return (actual['full_name']==expected['full_name'] and actual['parameter_type']==expected['parameter_type']
        and actual['overridden']==expected['overridden']
        and actual['uses_document_units']==expected['uses_document_units']
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


def collect_model_dimensions(views):
    """Read only dimensions attached to this task's model views, with limits."""
    result=[]
    for view_id,raw in views.items():
        view=_typed(raw,'IView');display=read_member(view,'GetFirstDisplayDimension5');seen=set()
        while display is not None:
            display=_typed(display,'IDisplayDimension')
            row=display_dimension_value(display)
            from .drawing_verification import annotation_evidence
            evidence=annotation_evidence(display,'model_dimension',{'view':view_id,'parameter':row['parameter']})
            identity=(evidence['name'],row['full_name'])
            if identity in seen or len(seen)>=512:raise RuntimeError('cyclic/oversized display dimension chain')
            seen.add(identity)
            result.append({**evidence,'model_dimension':row})
            display=read_member(display,'GetNext5')
    return result


def dimension_coverage(source,imported):
    expected=source['expected'];missing=list(source['missing_source_parameters']);issues=[]
    for item in expected:
        matches=[row['model_dimension'] for row in imported if row['model_dimension']['parameter']==item['parameter']]
        if not matches:missing.append(item['parameter']);continue
        if any(row['full_name']!=item['full_name'] or row['parameter_type']!=item['parameter_type']
               or not math.isclose(row['value_si'],item['value_si'],rel_tol=0,abs_tol=1e-9)
               or row['overridden'] or not row['uses_document_units'] for row in matches):
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
        return dimension_coverage({'expected':proof['source_parameters'],'missing_source_parameters':[]},rows)['status']=='verified'
    except (KeyError,TypeError,ValueError):return False
