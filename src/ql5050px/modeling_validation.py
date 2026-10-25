"""Pure pre-write validation; no COM/session imports."""
import math
from .feature_operations import validate_operations
from .sheet_feature_data import validate_extra


def number(value,positive=False):
    if type(value) not in (int,float) or not math.isfinite(value) or (positive and value<=0):raise ValueError('finite numeric value required')
    return float(value)


def point(value):
    if not isinstance(value,(list,tuple)) or len(value)!=2:raise ValueError('explicit 2D point required')
    return tuple(number(v) for v in value)


def envelope(value):
    if not isinstance(value,(list,tuple)) or len(value)!=3:raise ValueError('exactly three envelope dimensions required')
    return [number(v,True) for v in value]


def validate_part_plan(plan,supported):
    features=plan.get('features')
    if not isinstance(features,list) or not features:raise ValueError('nonempty editable feature plan required')
    if plan.get('pending_confirmation'):raise ValueError('pending feature confirmation')
    seen=set()
    for f in features:
        name=f.get('id')
        if not isinstance(name,str) or not name.strip() or name in seen:raise ValueError('nonempty unique feature names required')
        deps=f.get('depends_on',[])
        if name in deps or not set(deps)<=seen:raise ValueError('invalid feature dependency order')
        seen.add(name)
        if f.get('kind') not in supported or f.get('unit')!='mm' or f.get('confirmed') is not True or not f.get('evidence'):
            raise ValueError('supported, sourced and confirmed mm feature required')
        p=f.get('parameters',{})
        if f['kind']=='sketch':
            if not p.get('plane') or not p.get('entities'):raise ValueError('mapped plane and nonempty sketch required')
            for e in p['entities']:
                if e['type']=='line':
                    if point(e['start'])==point(e['end']):raise ValueError('zero-length sketch line')
                elif e['type']=='circle':point(e['center']);number(e['radius'],True)
                elif e['type']=='arc':
                    c,a,b=point(e['center']),point(e['start']),point(e['end'])
                    if a==b or type(e.get('direction')) is not int or e['direction'] not in (-1,1):raise ValueError('explicit nondegenerate arc required')
                    radius=math.dist(c,a)
                    if radius<=0 or not math.isclose(radius,math.dist(c,b),rel_tol=1e-7,abs_tol=1e-7):raise ValueError('arc endpoints must share a radius')
                else:raise ValueError('unsupported sketch entity')
        if f['kind'] in {'cut','extrude'}:
            number(p.get('depth_mm'),True)
            if p.get('sketch') not in deps:raise ValueError('consumed sketch must be an explicit predecessor')
        validate_extra(f)
    validate_operations(features)
    if plan.get('expected_dims_mm') is not None:envelope(plan['expected_dims_mm'])
    if 'expected_body_count' in plan and (type(plan['expected_body_count']) is not int or plan['expected_body_count']<1):raise ValueError('positive integer body count required')
    for row in plan.get('readback_dimensions',[]):
        if not row.get('name') or row.get('unit') not in {'mm','deg'}:raise ValueError('mapped length/angle dimension required')
        number(row['value'])
    return plan

