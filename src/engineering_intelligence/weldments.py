"""Straight-member weldment planning and conservative per-profile stock packing."""
import math
from .common import index, quantity, number, result


def plan_frame(request):
    profiles=index(request['profiles']); members=index(request['members'])
    kerf=quantity(request['kerf'],'mm',minimum=0)
    pending=[]; failures=[]; groups={}; cutlist=[]; features=[]; totals={}
    if not members: pending.append('no_frame_members')
    for key,row in members.items():
        profile=profiles[row['profile']]
        if not all(profile.get(k) for k in ('source','revision','material')):
            pending.append('unconfirmed_profile:'+profile['id'])
        area=quantity(profile['area'],'mm^2',minimum=0); density=quantity(profile['density'],'kg/m^3',minimum=0)
        stock=quantity(profile['stock_length'],'mm',minimum=0)
        start,end=row['start_mm'],row['end_mm']
        if len(start)!=3 or len(end)!=3: raise ValueError('frame endpoints require xyz mm')
        length=math.dist([number(x) for x in start],[number(x) for x in end])
        allowance=quantity(row['end_allowance'],'mm',minimum=0)
        cut=length+2*allowance; count=row['quantity']
        if type(count) is not int or count<=0 or min(length,area,density,stock)<=0:
            raise ValueError('positive profile/member geometry and integer quantity required')
        if not row.get('source'): pending.append('missing_member_source:'+key)
        if cut+kerf>stock: failures.append('member_exceeds_stock:'+key)
        # Unspecified miters/end trimming cannot silently become square cuts.
        if row.get('cut_type')!='square': pending.append('miter_or_trim_requires_review:'+key)
        mass=area*cut*1e-9*density*count
        totals[profile['material']]=totals.get(profile['material'],0)+mass
        cutlist.append({'member':key,'profile':profile['id'],'material':profile['material'],'cut_length_mm':cut,
                        'quantity':count,'net_mass_kg':mass,'cut_type':row.get('cut_type')})
        groups.setdefault(profile['id'],[]).extend([{'member':key,'length_mm':cut} for _ in range(count)])
        features.append({'id':key,'operation':'structural_member','profile':profile['id'],'profile_source':profile['source'],
                         'start_mm':start,'end_mm':end,'quantity':count,'confirmed':False})
    stock_plan=[]
    for pid,cuts in groups.items():
        stock=quantity(profiles[pid]['stock_length'],'mm',minimum=0); bars=[]
        for cut in sorted(cuts,key=lambda r:r['length_mm'],reverse=True):
            needed=cut['length_mm']+kerf
            if needed>stock: continue
            bar=next((b for b in bars if b['remaining_mm']>=needed),None)
            if bar is None: bar={'cuts':[],'remaining_mm':stock};bars.append(bar)
            bar['cuts'].append(cut);bar['remaining_mm']-=needed
        stock_plan.append({'profile':pid,'bars':bars,'stock_length_mm':stock,'stock_count':len(bars)})
    connections=[]
    for row in request.get('connections',[]):
        if len(row.get('members',[]))<2 or any(k not in members for k in row['members']): failures.append('invalid_weld_connection:'+row['id'])
        if not row.get('source') or not row.get('weld_spec'): pending.append('weld_procedure_missing:'+row['id'])
        connections.append(row)
    if not connections: pending.append('weld_connections_not_declared')
    return result({'cut_list':cutlist,'material_mass_kg':totals,'stock_plan':stock_plan,'connections':connections,
                   'native_feature_plan':{'operations':features,'execution':'pending_windows_validation','host':'existing_owned_host_required'},
                   'assumptions':['straight members only; first-fit decreasing, not optimal nesting',
                                  'kerf charged per cut conservatively; no weld strength/distortion or end-trim solver']},issues=pending,failed=failures)
