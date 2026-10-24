"""Evidence-preserving CAD feature planning; native execution uses owned host ports."""
import json,math,zipfile
from pathlib import Path


def geometry(request):
    entities=request.get('entities',[])
    if request.get('cad_path'):
        from cad_analyzer import analyze_cad_file
        analysis=analyze_cad_file(request['cad_path'])
        return {'source':'cad_analyzer','profiles':[{'index':i,'closed':p.closed,'evidence':repr(p)} for i,p in enumerate(analysis.profiles)],'status':'pending_confirmation','native_analysis':False}
    ids=set();groups={};issues=[]
    for entity in entities:
        if entity['id'] in ids:raise ValueError('duplicate source entity')
        ids.add(entity['id'])
        if entity['type'] not in {'line','circle','arc','polyline','dimension','block','centerline','bend'}:issues.append({'entity':entity['id'],'reason':'unsupported entity'})
        groups.setdefault(entity.get('layer','0'),[]).append(entity['id'])
        if entity['type']=='polyline' and entity.get('closed'):
            points=entity['points'];area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(points,points[1:]+points[:1]))/2
            if abs(area)<1e-8:issues.append({'entity':entity['id'],'reason':'degenerate contour'})
    if request.get('unit')!='mm' or request.get('scale')!=1:issues.append({'reason':'explicit mm and unit scale required'})
    return {'entities':entities,'groups':groups,'issues':issues,'hole_candidates':[e['id'] for e in entities if e['type']=='circle'],'status':'review_required','inferred_depth':None}


def feature_plan(request):
    supported={'sketch','extrude','cut','hole','fillet','chamfer','mirror','pattern','base_flange','edge_flange','sketched_bend','relief'}
    features={f['id']:f for f in request.get('features',[])};order=[];active=set();done=set();pending=[]
    if len(features)!=len(request.get('features',[])):raise ValueError('duplicate feature id')
    def visit(key):
        if key in active:raise ValueError('feature dependency cycle')
        if key in done:return
        if key not in features:raise ValueError('missing predecessor '+key)
        active.add(key);f=features[key]
        if f['kind'] not in supported:raise ValueError('unsupported feature kind')
        for dep in f.get('depends_on',[]):visit(dep)
        if not f.get('confirmed') or not f.get('evidence') or f.get('unit')!='mm':pending.append({'feature':key,'reason':'confirmed sourced dimensions required'})
        if f['kind'] in {'extrude','cut'} and not f.get('parameters',{}).get('depth_mm'):pending.append({'feature':key,'reason':'depth missing; no multi-view guessing'})
        if f['kind'] in {'base_flange','edge_flange','sketched_bend'}:
            for name in ('thickness_mm','radius_mm','k_factor','direction'):
                if f.get('parameters',{}).get(name) is None:pending.append({'feature':key,'field':name})
        active.remove(key);done.add(key);order.append({**f,'fallback':'stop_and_preserve_diagnostics'})
    for key in features:visit(key)
    if not features:pending.append({'reason':'no uniquely reconstructable feature sequence'})
    return {'features':order,'pending_confirmation':pending,'status':'pending_confirmation' if pending else 'ready_for_native','native_validation':'pending_native_validation'}


def manufacturing_rules(inputs,standard=None):
    standard=standard or {};rows=[]
    checks=[('thickness_mm','min_thickness_mm'),('radius_mm','min_radius_mm'),('relief_width_mm','min_relief_width_mm'),('relief_depth_mm','min_relief_depth_mm'),('hole_bend_distance_mm','min_hole_bend_distance_mm'),('flange_mm','min_flange_mm')]
    for field,limit in checks:
        value=inputs.get(field);bound=standard.get(limit)
        rows.append({'rule':field,'value':value,'unit':'mm','basis':standard.get('source'),'minimum':bound,
            'status':'pending_confirmation' if value is None or bound is None else ('passed' if value>=bound else 'failed'),'suggested_value':bound})
    k=inputs.get('k_factor');rows.append({'rule':'k_factor','value':k,'unit':'ratio','status':'pending_confirmation' if k is None else ('passed' if 0<=k<=1 else 'failed')})
    return {'rules':rows,'manufacturing_approved':False,'warnings':['No plant standard means advisory only. Self-intersection and folded collision require geometry/native checks.']}


def diagnose(records):
    catalogue={'rebuild':('invalid reference','inspect first failed feature and dependencies'),'overdefined':('conflicting constraints','review redundant constraints without deleting automatically'),'underdefined':('missing sketch constraints','identify free dimensions'),'bend':('bend position/fixed face/relief mismatch','compare centerline and outside positioning in isolated copies'),'mate':('mate conflict','check references and remaining DOF')}
    reports=[]
    for record in records:
        text=str(record).lower();causes=[{'hypothesis':v[0],'recommendation':v[1],'confidence':0.5,'evidence':record} for k,v in catalogue.items() if k in text]
        reports.append({'location':record.get('feature'),'native_code':record.get('code'),'reproduction':record.get('reproduction'),'possible_causes':causes,'root_cause_confirmed':False,'auto_repair':False})
    return reports


def execute_part(plan,port,destination):
    """Host port enforces owned STA, isolated new output, checkpoint and readback."""
    if plan['pending_confirmation']:raise ValueError('unconfirmed geometry cannot execute')
    with port.writer():
        port.preflight([],str(destination));checkpoint=port.checkpoint()
        try:
            for feature in plan['features']:port.guarded('create_editable_feature',feature)
            port.rebuild();port.save_as(str(destination));port.reopen(str(destination))
            evidence=port.guarded('verify_feature_tree',[f['id'] for f in plan['features']])
            return {'evidence':evidence,'status':'pending_native_validation'}
        except Exception:
            port.restore(checkpoint);raise


def run_cad_features(request,output_dir=None):
    result={'geometry':geometry(request),'feature_plan':feature_plan(request),'manufacturing':manufacturing_rules(request.get('sheet',{}),request.get('standard')),'diagnostics':diagnose(request.get('errors',[])),'status':'pending_confirmation','cad_executed':False,'plan':{},'tests':'not_run'}
    if output_dir:
        root=Path(output_dir);root.mkdir(parents=True,exist_ok=False)
        for key,value in result.items():(root/(key+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
        with zipfile.ZipFile(root/'gork-cad-features.zip','x',zipfile.ZIP_DEFLATED) as z:
            for p in root.glob('*.json'):z.write(p,p.name)
    return result
