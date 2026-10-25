"""Reuse engineering calculations; add sourced shaft deflection/cylinder/guide sizing."""
import math
from ql5050px.mechanical_selection import calculate


def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite numeric engineering value required')
    return float(value)


def compute(kind,inputs):
    specs={'shaft_deflection':{'force':'N','span':'mm','diameter':'mm','elastic_modulus':'MPa'},
        'cylinder':{'pressure':'MPa','bore':'mm','rod':'mm','efficiency':'ratio','required_force':'N','safety':'ratio'},
        'guide':{'force':'N','carriages':'count','rating':'N','safety':'ratio'}}
    if kind not in specs:return calculate(kind,inputs)
    missing=[key for key in specs[kind] if key not in inputs]
    if missing:return {'status':'pending_input','missing':missing,'engineering_approved':False}
    values={}
    for key,unit in specs[kind].items():
        row=inputs[key]
        if row.get('unit')!=unit or not row.get('source'):raise ValueError('explicit unit/source required: '+key)
        values[key]=number(row['value'])
        if values[key]<=0:raise ValueError('positive input required: '+key)
    v=values
    if kind=='shaft_deflection':
        inertia=math.pi*v['diameter']**4/64
        results={'center_deflection_mm':v['force']*v['span']**3/(48*v['elastic_modulus']*inertia),
                 'max_bending_stress_MPa':8*v['force']*v['span']/(math.pi*v['diameter']**3)}
        assumptions=['simply supported uniform solid round shaft; static central point load; no fatigue/keyway analysis']
    elif kind=='cylinder':
        if v['rod']>=v['bore'] or v['efficiency']>1 or v['safety']<1:raise ValueError('invalid cylinder geometry/efficiency/safety')
        push=v['pressure']*math.pi*v['bore']**2/4*v['efficiency']
        pull=v['pressure']*math.pi*(v['bore']**2-v['rod']**2)/4*v['efficiency']
        required=v['required_force']*v['safety']
        results={'push_N':push,'pull_N':pull,'required_design_force_N':required,'push_sufficient':push>=required,'pull_sufficient':pull>=required}
        assumptions=['static pressure force; no buckling, acceleration, friction curve or air-supply sizing']
    else:
        if int(v['carriages'])!=v['carriages'] or v['safety']<1:raise ValueError('integer carriage count and safety>=1 required')
        load=v['force']/v['carriages']*v['safety']
        results={'design_load_per_carriage_N':load,'rating_sufficient':v['rating']>=load}
        assumptions=['equal static load sharing only; moments, mounting compliance and life require review']
    return {'kind':kind,'inputs':inputs,'results':results,'assumptions':assumptions,'status':'preliminary_selection','engineering_approved':False}
