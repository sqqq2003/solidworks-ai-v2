"""Bounded, pure modeling admission. Estimates never become native evidence."""
from copy import deepcopy
import hashlib
import math
import re

from cad_checkpoint import json_bytes
from ql5050px.modeling_validation import validate_part_plan,number

KINDS=frozenset({'sketch','extrude','cut','revolve'})
NAME=re.compile(r'AI_[A-Za-z0-9_]{1,60}\Z')
MAX_FEATURES=32


def digest(value):return hashlib.sha256(json_bytes(value)).hexdigest()


def capabilities():
    return {'domain':'modeling','contract_version':1,'operations':sorted(KINDS),
            'max_features':MAX_FEATURES,'public_calls':['analyze_draft','run_transaction','observe','body_clearance'],
            'checkpoint_required':True,'expected_revision_required':True,
            'sheet_operations':False,'arbitrary_native_properties':False,'manufacturing_approved':False}


def validate_plan(plan):
    plan=deepcopy(plan)
    if plan.get('domain')!='modeling' or plan.get('contract_version')!=1:
        raise ValueError('explicit modeling contract version 1 required')
    features=plan.get('features')
    if not isinstance(features,list) or not 1<=len(features)<=MAX_FEATURES:raise ValueError('bounded nonempty feature list required')
    # Reuse existing sketch/extrusion/unit/dependency validation. Revolve has a
    # fixed typed call below, rather than arbitrary CreateDefinition properties.
    revolved={f.get('id') for f in features if f.get('kind')=='revolve'}
    ordinary={**plan,'features':[{**f,'depends_on':[d for d in f.get('depends_on',[]) if d not in revolved]}
                               for f in features if f.get('kind')!='revolve']}
    if ordinary['features']:validate_part_plan(ordinary,KINDS)
    if features[-1].get('kind')=='sketch':raise ValueError('plan must finish with a verified solid operation')
    seen=set();body_names=set();sketches={}
    for f in features:
        name=f.get('id');kind=f.get('kind');p=f.get('parameters',{})
        if not isinstance(name,str) or not NAME.fullmatch(name) or name in seen:raise ValueError('unique AI_ feature identity required')
        if kind not in KINDS or not set(f.get('depends_on',[]))<=seen:raise ValueError('unknown operation or unordered dependencies')
        if f.get('unit')!='mm' or f.get('confirmed') is not True or not f.get('evidence'):raise ValueError('confirmed sourced mm feature required')
        if kind=='sketch':
            sketches[name]=p
            if len(p.get('entities',[]))>256:raise ValueError('sketch entity limit exceeded')
            for e in p.get('entities',[]):
                if 'construction' in e and type(e['construction']) is not bool:raise ValueError('explicit construction boolean required')
            for row in p.get('constraints',[]):
                for ref in row['references']:
                    if (ref.get('type') not in {'SKETCHSEGMENT','SKETCHPOINT'} or
                            not ref.get('name','').endswith('@'+name) or ref.get('mark',0)!=0):
                        raise ValueError('constraint must reference a segment/point of its owned sketch')
        if kind in {'extrude','cut','revolve'}:
            if p.get('sketch') not in f.get('depends_on',[]):raise ValueError('consumed sketch dependency required')
            if p.get('sketch') not in sketches:raise ValueError('consumed feature must be an owned sketch')
            expected=f.get('expected')
            if not isinstance(expected,dict):raise ValueError('independent native body expectations required')
            names=expected.get('body_names')
            if not isinstance(names,list) or not names or len(names)!=len(set(names)) or any(not isinstance(n,str) or not NAME.fullmatch(n) for n in names):
                raise ValueError('unique explicit AI_ body names required')
            if type(expected.get('min_faces')) is not int or expected['min_faces']<1:raise ValueError('positive face-count gate required')
            number(expected.get('min_volume_mm3'),True)
            if number(expected.get('max_volume_mm3'),True)<expected['min_volume_mm3']:
                raise ValueError('volume interval inverted')
            if expected.get('bounds_mm') is None:raise ValueError('independent bbox gate required')
            if expected.get('bounds_mm') is not None:
                bounds=expected['bounds_mm']
                if not isinstance(bounds,list) or len(bounds)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds) or any(bounds[i+3]<=bounds[i] for i in range(3)):
                    raise ValueError('six ordered bbox limits required')
                number(expected.get('bbox_tolerance_mm',.05),True)
            if kind=='cut' and not body_names:raise ValueError('cut cannot target an unowned initial body')
            if kind=='cut' and set(names)!=body_names:raise ValueError('cut must preserve the owned body set')
            if kind!='cut' and body_names and not body_names<=set(names):raise ValueError('owned body identity cannot silently disappear')
            body_names=set(names)
        if kind=='extrude' and type(p.get('merge')) is not bool:raise ValueError('explicit merge boolean required')
        if kind=='cut' and type(p.get('reverse',False)) is not bool:raise ValueError('explicit cut reverse boolean required')
        if kind=='revolve':
            angle=number(p.get('angle_degrees'),True)
            if angle>360 or type(p.get('merge')) is not bool:raise ValueError('bounded revolve angle and merge required')
            axis=p.get('axis')
            if not isinstance(axis,dict) or axis.get('type')!='SKETCHSEGMENT' or not isinstance(axis.get('name'),str) or not axis['name'].endswith('@'+p['sketch']):
                raise ValueError('explicit named sketch-segment revolve axis required')
            line=axis['name'].rsplit('@',1)[0]
            matches=[e for e in sketches[p['sketch']]['entities'] if e.get('native_name')==line]
            if len(matches)!=1 or matches[0].get('type')!='line' or matches[0].get('construction') is not True:
                raise ValueError('revolve axis must map one explicit construction line in consumed sketch')
        # No hidden fallback or arbitrary COM member arguments in the narrow plan.
        if any(k in p for k in ('native_properties','native_feature_id','macro','script','method')):
            raise ValueError('raw native commands not in modeling contract')
        seen.add(name)
    return plan


def _area(entities):
    entities=[e for e in entities if not e.get('construction')]
    if len(entities)==1 and entities[0]['type']=='circle':return math.pi*entities[0]['radius']**2
    if not entities or any(e['type']!='line' for e in entities):return None
    if any(tuple(a['end'])!=tuple(b['start']) for a,b in zip(entities,entities[1:]+entities[:1])):return None
    from profile_sanitize import contour_self_intersects
    if contour_self_intersects(tuple(tuple(e['start']) for e in entities)):return None
    return abs(sum(e['start'][0]*e['end'][1]-e['end'][0]*e['start'][1] for e in entities)/2)


def analyze_draft(plan,*,revision=None,inventory=None):
    plan=validate_plan(plan);sketches={};estimates=[];conflicts=[]
    for feature in plan['features']:
        kind=feature['kind'];p=feature['parameters']
        if kind=='sketch':sketches[feature['id']]=p['entities']
        if kind in {'extrude','cut'}:
            area=_area(sketches.get(p['sketch'],[]))
            if area is None or area<=0:conflicts.append({'feature':feature['id'],'reason':'closed_profile_area_not_established'})
            estimates.append({'feature':feature['id'],'estimated_volume_mm3':None if area is None else area*p['depth_mm'],
                              'scope':'draft_swept_volume_only_not_boolean_or_acceptance'})
        if kind=='revolve':
            area=_area(sketches[p['sketch']])
            if area is None or area<=0:conflicts.append({'feature':feature['id'],'reason':'closed_revolve_profile_not_established'})
            entities=sketches[p['sketch']]
            axis=next(e for e in entities if e.get('native_name')==p['axis']['name'].rsplit('@',1)[0])
            a,b=axis['start'],axis['end'];dx,dy=b[0]-a[0],b[1]-a[1]
            def side(point):return (dx*(point[1]-a[1])-dy*(point[0]-a[0]))/math.hypot(dx,dy)
            distances=[]
            for e in entities:
                if e.get('construction'):continue
                if e['type']=='line':distances.extend((side(e['start']),side(e['end'])))
                if e['type']=='circle':distances.extend((side(e['center'])-e['radius'],side(e['center'])+e['radius']))
            if distances and min(distances)<-1e-7 and max(distances)>1e-7:
                conflicts.append({'feature':feature['id'],'reason':'revolve_profile_crosses_reviewed_axis'})
            estimates.append({'feature':feature['id'],'estimated_volume_mm3':None,
                              'scope':'revolve_self_intersection_requires_native_geometry'})
    compatibility=edit_compatibility(inventory or {'features':[],'bodies':[]},[])
    if inventory and inventory.get('bodies'):conflicts.append({'reason':'nonempty_initial_model_requires_separate_reviewed_edit_workflow'})
    return {'domain':'modeling','plan':plan,'plan_sha256':digest(plan),'expected_revision':revision,
            'status':'blocked' if conflicts else 'draft_ready','conflicts':conflicts,'estimates':estimates,
            'edit_compatibility':compatibility,'estimated_geometry_is_acceptance':False,
            'native_executed':False,'manufacturing_approved':False}


def edit_compatibility(inventory,owned_features):
    owned=set(owned_features);rows=inventory.get('features',[])
    unknown=[r['name'] for r in rows if r.get('name') not in owned]
    return {'status':'review_required' if unknown else 'compatible','owned_features':sorted(owned),
            'protected_or_unknown_features':unknown,'may_modify_existing_features':False,
            'policy':'append_only_named_features; no deletion, suppression or topology repair'}


def verify_bodies(rows,expected):
    if not isinstance(rows,list) or {r.get('name') for r in rows}!=set(expected['body_names']) or len(rows)!=len(expected['body_names']):
        raise RuntimeError('native named body set differs')
    for row in rows:
        if type(row.get('faces')) is not int or row['faces']<expected['min_faces']:raise RuntimeError('native face-count gate failed')
        volume=number(row.get('volume_mm3'),True)
        if volume<expected['min_volume_mm3'] or volume>expected.get('max_volume_mm3',math.inf):raise RuntimeError('native volume gate failed')
        bounds=row.get('bounds_mm')
        if not isinstance(bounds,list) or len(bounds)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds) or any(bounds[i+3]<=bounds[i] for i in range(3)):
            raise RuntimeError('native bbox is invalid')
    if expected.get('bounds_mm'):
        union=[min(r['bounds_mm'][i] for r in rows) for i in range(3)]+[max(r['bounds_mm'][i] for r in rows) for i in range(3,6)]
        if any(abs(a-b)>expected.get('bbox_tolerance_mm',.05) for a,b in zip(union,expected['bounds_mm'])):raise RuntimeError('native bbox differs from independent expectation')
    return {'named_bodies':rows,'bounds_precision':'approximate','engineering_accepted':False}
