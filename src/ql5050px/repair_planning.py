"""Conservative cylinder/slot trial plans; no COM, no production approval."""
import math
import re

def number(value, label, *, positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(label+' must be a finite number')
    if positive and value<=0:raise ValueError(label+' must be positive')
    return float(value)

def vector(values,label,size):
    if not isinstance(values,(list,tuple)) or len(values)!=size:raise ValueError(label+' has wrong length')
    return [number(v,label) for v in values]

def plan_slot_relief(*,source_sha256,axis_point_mm,axis_direction,cylinder_radius_mm,
        slot_center_mm,existing_radius_mm,slab_z_mm,trial_clearance_mm,
        radius_grid_mm,max_trial_increase_mm,trial_authorized=False):
    """Bound a tilted cylinder's intersection with a plate in local XY/Z.

    Triangle inequality + the ellipse semimajor axis conservatively encloses the
    infinite cylinder at both plate surfaces. Finite ends are not assumed clear.
    This sizes a candidate U-slot/circular relief; it cannot certify strength,
    manufacturing clearance, or the rest of the assembly.
    """
    if not isinstance(source_sha256,str) or not re.fullmatch('[0-9a-fA-F]{64}',source_sha256):raise ValueError('verified source SHA256 required')
    p=vector(axis_point_mm,'axis point',3);a=vector(axis_direction,'axis direction',3)
    center=vector(slot_center_mm,'slot center',2);slab=vector(slab_z_mm,'plate surfaces',2)
    if slab[1]<=slab[0]:raise ValueError('ordered distinct plate surfaces required')
    if not isinstance(trial_authorized,bool):raise ValueError('trial authorization must be a boolean')
    norm=math.hypot(*a)
    if norm<1e-12:raise ValueError('nonzero axis direction required')
    a=[x/norm for x in a]
    if abs(a[2])<1e-6:raise ValueError('axis nearly parallel to plate; finite-body analysis required')
    radius=number(cylinder_radius_mm,'cylinder radius',positive=True)
    existing=number(existing_radius_mm,'existing radius',positive=True)
    clearance=number(trial_clearance_mm,'trial clearance')
    if clearance<0:raise ValueError('negative clearance refused')
    grid=number(radius_grid_mm,'radius grid',positive=True);limit=number(max_trial_increase_mm,'trial increase limit',positive=True)
    intersections=[[p[i]+a[i]*(z-p[2])/a[2] for i in range(3)] for z in slab]
    offset=max(math.hypot(q[0]-center[0],q[1]-center[1]) for q in intersections)
    bound=number(offset+radius/abs(a[2]),'computed radius')
    number((bound+clearance)/grid,'computed radius grid ratio')
    target=max(existing,math.ceil((bound+clearance)/grid-1e-12)*grid)
    increase=target-existing
    status='no_change' if increase==0 else 'ready_for_trial' if trial_authorized is True and increase<=limit+1e-9 else 'review_required'
    return {'schema_version':1,'operation':'local_slot_relief','units':'mm','source_sha256':source_sha256.lower(),
        'profile_frame':'slot plane XY; thickness along Z','axis_point_mm':p,'axis_direction':a,
        'slot_center_mm':center,'plate_surfaces_z_mm':slab,'axis_intersections_mm':intersections,
        'cylinder_radius_mm':radius,'ellipse_semimajor_mm':radius/abs(a[2]),
        'conservative_required_radius_mm':bound,'existing_radius_mm':existing,
        'target_radius_mm':target,'radius_increase_mm':increase,'trial_clearance_mm':clearance,
        'trial_clearance_source':'explicit_test_assumption_not_manufacturing_tolerance',
        'radius_grid_mm':grid,'max_trial_increase_mm':limit,'status':status,
        'trial_authorized':trial_authorized is True,'cad_executed':False,'production_approved':False,
        'engineering_confirmation':'pending','not_checked':['material','ligament strength','production tolerances','other interfaces','whole-machine clearance']}

def require_trial(plan,actual_source_sha256):
    """Recompute derived fields: an edited plan must never bypass the size gate."""
    if not isinstance(plan,dict):raise ValueError('repair plan must be an object')
    if not isinstance(actual_source_sha256,str) or not re.fullmatch('[0-9a-fA-F]{64}',actual_source_sha256):raise ValueError('verified current source SHA256 required')
    if plan.get('status')!='ready_for_trial' or plan.get('trial_authorized') is not True:raise ValueError('repair is not authorized for trial execution')
    if plan.get('units')!='mm' or plan.get('production_approved') is not False:raise ValueError('invalid trial-only repair plan')
    if plan['source_sha256']!=actual_source_sha256.lower():raise ValueError('repair source baseline changed')
    if plan.get('engineering_confirmation')!='pending':raise ValueError('unexpected repair confirmation state')
    keys=('source_sha256','axis_point_mm','axis_direction','cylinder_radius_mm',
          'slot_center_mm','existing_radius_mm','trial_clearance_mm','radius_grid_mm',
          'max_trial_increase_mm','trial_authorized')
    try:
        inputs={key:plan[key] for key in keys}
        inputs['slab_z_mm']=plan['plate_surfaces_z_mm']
        rebuilt=plan_slot_relief(**inputs)
    except (KeyError,TypeError,OverflowError) as error:
        raise ValueError('incomplete or invalid repair plan') from error
    # Re-normalizing a unit vector can introduce a few ulps. Compare numerical
    # evidence tightly while requiring every semantic gate to remain identical.
    def equal(a,b):
        if isinstance(a,bool) or isinstance(b,bool):return a is b
        if isinstance(a,(int,float)) and isinstance(b,(int,float)):
            return math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
        if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
        return a==b
    if any(key not in plan or not equal(plan[key],value) for key,value in rebuilt.items()):
        raise ValueError('repair plan evidence does not match recomputed inputs')
    return True
