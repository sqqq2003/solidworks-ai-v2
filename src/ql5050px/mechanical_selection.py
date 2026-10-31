"""Preliminary engineering calculations and user-supplied catalogue selection."""
import csv,json,math
from pathlib import Path


def positive(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0: raise ValueError('finite positive input required')
    return value


def calculate(kind, inputs):
    """Each input is {value, unit, source}; reject unit guessing and missing data."""
    specs={'conveyor':{'diameter':'mm','rpm':'rpm'},'ratio':{'driver':'count','driven':'count'},
        'motor':{'force':'N','speed':'m/s','efficiency':'ratio','rpm':'rpm','safety':'ratio'},
        'shaft':{'torque':'N*m','bending':'N*m','allowable_shear':'MPa','safety':'ratio'},
        'bearing':{'dynamic_rating':'N','equivalent_load':'N','rpm':'rpm','exponent':'ratio'},
        'belt':{'diameter_1':'mm','diameter_2':'mm','center':'mm'},
        'chain':{'pitch':'mm','teeth_1':'count','teeth_2':'count','center':'mm'},
        'shaft_load':{'force':'N','span':'mm','position':'mm'}}
    if kind not in specs: raise ValueError('unsupported mechanical calculation')
    missing=[n for n in specs[kind] if n not in inputs]
    if missing: return {'status':'pending_input','missing':missing,'engineering_approved':False}
    v={}
    for name,unit in specs[kind].items():
        row=inputs[name]
        if row.get('unit')!=unit or not row.get('source'): raise ValueError('explicit unit and source required for '+name)
        v[name]=positive(row['value'])
    warnings=[]
    if kind=='conveyor': result={'speed_mm_s':math.pi*v['diameter']*v['rpm']/60}
    elif kind=='ratio': result={'output_input_ratio':v['driver']/v['driven']}
    elif kind=='motor':
        if v['efficiency']>1 or v['safety']<1: raise ValueError('efficiency <=1 and safety >=1 required')
        power=v['force']*v['speed']/v['efficiency']*v['safety']
        result={'power_W':power,'torque_Nm':power/(2*math.pi*v['rpm']/60)}
    elif kind=='shaft':
        equivalent=math.hypot(v['torque'],v['bending'])*1000*v['safety']
        result={'diameter_mm':(16*equivalent/(math.pi*v['allowable_shear']))**(1/3)}
        warnings.append('Solid circular shaft, maximum shear criterion; fatigue/keyways/deflection not covered.')
    elif kind=='bearing':
        life=(v['dynamic_rating']/v['equivalent_load'])**v['exponent']
        result={'L10_million_revolutions':life,'L10_hours':life*1e6/(60*v['rpm'])}
        warnings.append('Basic rating life only; lubrication, contamination and axial-load factors require review.')
    elif kind=='shaft_load':
        if v['position']>=v['span']: raise ValueError('load must lie inside support span')
        right=v['force']*v['position']/v['span']
        result={'left_reaction_N':v['force']-right,'right_reaction_N':right,
                'max_bending_Nm':(v['force']-right)*v['position']/1000}
    else:
        from .drive_variant import compute
        if kind=='belt': result={'theoretical_length_mm':compute({'op':'open_belt_length'},[v[k] for k in ('diameter_1','diameter_2','center')])}
        else: result={'theoretical_links':compute({'op':'chain_links'},[v[k] for k in ('pitch','teeth_1','teeth_2','center')])}
        warnings.append('Geometric preliminary estimate; tension, load capacity and standard lengths not selected.')
    return {'kind':kind,'inputs':inputs,'results':result,'warnings':warnings,
            'status':'preliminary_selection','engineering_approved':False}


def select_catalogue(path, requirements):
    """Requirements: {field, unit, minimum?, maximum?}; missing fields rejected."""
    path=Path(path)
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as stream: rows=list(csv.DictReader(stream))
    else: rows=json.loads(path.read_text(encoding='utf-8-sig'))
    accepted,rejected=[],[]
    for row in rows:
        reasons=[]
        if not row.get('model') or not row.get('source'): reasons.append('missing model/source')
        for req in requirements:
            field=req['field']
            if row.get(field) in (None,'') or row.get(field+'_unit')!=req['unit']:
                reasons.append(field+': missing value/unit'); continue
            value=float(row[field])
            if not math.isfinite(value) or value<req.get('minimum',-math.inf) or value>req.get('maximum',math.inf): reasons.append(field+': out of range')
        (rejected if reasons else accepted).append({'specification':row,'reasons':reasons})
    return {'candidates':accepted,'rejected':rejected,'status':'review_required','engineering_approved':False}
