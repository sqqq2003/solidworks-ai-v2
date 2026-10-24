"""Complete synthetic/reviewed part recipes compiled into existing native engines.

Dimensions are explicit recipe inputs, never inferred OEM geometry. Template
plane names and executable paths remain deployment bindings requiring review.
"""
from copy import deepcopy
import hashlib,json,math

FAMILIES={'plate','bracket','shaft','two_bend_sheet'}


def positive(value,name):
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError(name+' must be finite positive')
    return float(value)


def approval_digest(recipe,bindings):
    return hashlib.sha256(json.dumps({'recipe':recipe,'bindings':bindings},sort_keys=True,allow_nan=False).encode()).hexdigest()


def lines(points):
    return [{'type':'line','start':a,'end':b} for a,b in zip(points,points[1:]+points[:1])]


def compile_recipe(recipe,bindings=None):
    bindings=bindings or {};kind=recipe['kind']
    if kind not in FAMILIES:raise ValueError('unsupported recipe')
    if recipe.get('units')!='mm' or not recipe.get('source'):raise ValueError('explicit mm and dimension source required')
    pending=[];features=[];backend='feature_ir';payload={}
    def feature(name,kind,parameters,depends=()):
        f={'id':name,'kind':kind,'unit':'mm','confirmed':recipe.get('dimensions_confirmed') is True,
            'evidence':[recipe['source']],'depends_on':list(depends),'parameters':parameters}
        features.append(f);return name
    plane=bindings.get('sketch_plane')
    if recipe.get('dimensions_confirmed') is not True:pending.append('dimensions_confirmation')
    if kind in {'plate','bracket'}:
        if not plane:pending.append('template_sketch_plane')
        length=positive(recipe['length_mm'],'length');width=positive(recipe['width_mm'],'width')
        thickness=positive(recipe['thickness_mm'],'thickness')
        if kind=='plate':outline=[[0,0],[length,0],[length,width],[0,width]]
        else:
            leg=positive(recipe['leg_mm'],'leg')
            if leg>=min(length,width):raise ValueError('bracket leg must leave positive inner opening')
            outline=[[0,0],[length,0],[length,leg],[leg,leg],[leg,width],[0,width]]
        sketch=feature('outline','sketch',{'plane':plane,'entities':lines(outline)})
        body=feature('body','extrude',{'sketch':sketch,'depth_mm':thickness},[sketch])
        circles=[]
        for hole in recipe.get('holes',[]):
            x,y=hole['center_mm'];radius=positive(hole['diameter_mm'],'diameter')/2
            if not (radius<x<length-radius and radius<y<width-radius):raise ValueError('hole intersects outer envelope')
            if kind=='bracket' and x+radius>leg and y+radius>leg:raise ValueError('hole crosses L-bracket opening')
            circles.append({'type':'circle','center':[x,y],'radius':radius})
        if circles:
            sketch=feature('hole_sketch','sketch',{'plane':plane,'entities':circles},[body])
            feature('holes','cut',{'sketch':sketch,'depth_mm':thickness,'reverse':True},[sketch])
        payload={'outline_mm':outline,'thickness_mm':thickness,'holes':recipe.get('holes',[])}
    elif kind=='shaft':
        backend='turned_generator';profile=[[0,0]];cursor=0
        for stage in recipe['stages']:
            length=positive(stage['length_mm'],'stage length');radius=positive(stage['diameter_mm'],'stage diameter')/2
            profile.extend([[cursor,radius],[cursor+length,radius]]);cursor+=length
        if cursor==0:raise ValueError('shaft needs stages')
        profile.extend([[cursor,0],[0,0]]);payload={'profile_mm':profile,'axis':'horizontal','axis_position':0}
        feature('half_profile','sketch',{'profile_mm':profile,'axis':'horizontal'})
        feature('shaft','revolve',{'angle_deg':360,'profile':'half_profile'},['half_profile'])
    else:
        backend='sheet_pipeline'
        length=positive(recipe['length_mm'],'length');width=positive(recipe['width_mm'],'width')
        t=positive(recipe['thickness_mm'],'thickness');r=positive(recipe['radius_mm'],'radius')
        k=recipe['k_factor']
        if type(k) not in (float,int) or not 0<=k<=1:raise ValueError('K must be explicit in [0,1]')
        positions=recipe['bend_positions_mm']
        if len(positions)!=2 or not 0<positions[0]<positions[1]<length:raise ValueError('two ordered interior bends required')
        if type(recipe.get('flip_direction')) is not bool:pending.append('bend_direction')
        angle=positive(recipe['angle_deg'],'bend angle')
        if angle>=180:raise ValueError('bend angle must be below 180')
        payload={'length_mm':length,'width_mm':width,'thickness_mm':t,'radius_mm':r,'k_factor':k,
            'angle_deg':angle,'bend_positions_mm':positions,'flip_direction':recipe.get('flip_direction'),
            'relief_bend_indices':recipe.get('relief_bend_indices',[])}
        feature('blank','sketch',{'entities':lines([[0,0],[length,0],[length,width],[0,width]])})
        feature('sheet','base_flange',{'thickness_mm':t,'radius_mm':r,'k_factor':k},['blank'])
        feature('bend_1','sketched_bend',{'position_mm':positions[0],'angle_deg':angle},['sheet'])
        feature('bend_2','sketched_bend',{'position_mm':positions[1],'angle_deg':angle},['bend_1'])
    # Recipe routes shaft/sheet through established generators rather than
    # pretending incomplete generic feature-data maps are executable fixtures.
    if kind in {'plate','bracket'} and not bindings.get('template'):pending.append('part_template')
    return {'recipe':deepcopy(recipe),'bindings':deepcopy(bindings),'backend':backend,'features':features,
        'payload':payload,'expected_dims_mm':[length,width,thickness] if kind in {'plate','bracket'} else None,'expected_body_count':1,
        'pending_confirmation':pending,'status':'pending_confirmation' if pending else 'ready_for_native_review',
        'native_acceptance':'pending_windows_validation','approval_digest':approval_digest(recipe,bindings)}


def simulate_recipe(recipe,bindings=None):
    plan=compile_recipe(recipe,bindings)
    return {'kind':recipe['kind'],'backend':plan['backend'],'feature_sequence':[f['kind'] for f in plan['features']],
            'payload':plan['payload'],'pending_confirmation':plan['pending_confirmation'],
            'status':'offline_plan_generated','cad_executed':False,'native_acceptance':'pending_windows_validation'}
