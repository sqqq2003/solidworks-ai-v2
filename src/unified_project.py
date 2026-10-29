"""Offline release orchestration across existing modules; no CAD/COM execution."""
from copy import deepcopy
import hashlib
import json
import subprocess
from pathlib import Path
import zipfile
from design_review import analyze_impact
from design_review.impact import review_digest
from ql5050px.integrated import run_integrated
from roller_variant import plan_variant
from roller_variant.delivery import export_package
from engineering_intelligence import build_batch
from design_platform.workflow import build_delivery


def roller_chain(plan):
    """Translate explicit measured roller sum to dimension IR; never OEM inference."""
    keys=['barrel_length','left_projection','right_projection',*plan['protected_parameters']]
    keys=list(dict.fromkeys(keys));before=plan['before_mm'];request=plan['request']
    if any(k not in before for k in keys):raise ValueError('roller chain requires measured core/protected values')
    mappings={r['parameter']:r for r in request['mappings']['parameters']}
    rows=[]
    for key in keys:
        measured=request['measurements'][key]
        if measured.get('confirmed') is not True or not measured.get('source'):
            raise ValueError('roller chain cannot confirm an unreviewed measurement')
        row={'id':key,'value':before[key],'unit':'mm','datum':'roller_axis:'+request['axis'],
             'source':measured['source'],'role':'adjustable' if key=='barrel_length' else 'interface'}
        bounds=mappings.get(key,{}).get('allowed_range')
        if bounds is not None:row.update(minimum_mm=bounds[0],maximum_mm=bounds[1])
        rows.append(row)
    rows.append({'id':'overall_length','value':before['overall_length'],'unit':'mm',
        'datum':'roller_axis:'+request['axis'],'source':'explicit roller barrel + two projections definition',
        'role':'adjustable','terms':[{'dimension':k,'direction':1} for k in ('barrel_length','left_projection','right_projection')],
        'solve_for':'barrel_length'})
    return {'dimensions':rows,'targets':{'overall_length':{'value':plan['target_overall_mm'],'unit':'mm','source':'reviewed roller request target'}}}


def build_release(request, destination):
    if request.get('schema_version')!=1:raise ValueError('release schema_version must be 1')
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    results={};errors=[]
    def stage(name,call):
        try:value=call()
        except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
            value={'status':'failed','error':type(exc).__name__+': '+str(exc)};errors.append(name)
        results[name]=value;return value
    if 'machine' in request:stage('machine',lambda:run_integrated(request['machine'],root/'machine'))
    roller=None
    if 'roller' in request:
        roller=stage('roller',lambda:plan_variant(request['roller']))
        if roller.get('status')!='failed':
            stage('roller_package',lambda:export_package(request['roller'],root/'roller'))
            if 'roller_intentions' in request:stage('roller_impact',lambda:analyze_impact(roller,request['roller_intentions']))
    engineering=deepcopy(request.get('engineering',{'modules':{}}))
    if request.get('link_roller_dimensions'):
        if roller is None or roller.get('status')=='failed':
            results['dimension_link']={'status':'failed','error':'roller plan required'};errors.append('dimension_link')
        else:
            linked=stage('dimension_link',lambda:roller_chain(roller))
            if 'dimensions' in linked:
                # Reject conflicting independently supplied chain; no silent overwrite.
                supplied=engineering['modules'].get('dimensions')
                if supplied is not None and review_digest(supplied)!=review_digest(linked):
                    results['dimension_link']={'status':'failed','error':'engineering chain conflicts with linked roller baseline'};errors.append('dimension_link')
                else:engineering['modules']['dimensions']=linked
    if engineering.get('modules'):stage('engineering',lambda:build_batch(engineering,root/'engineering'))
    platform=deepcopy(request.get('platform',{}))
    if request.get('link_machine_manufacturing'):
        machine=results.get('machine',{}).get('machine_plan')
        if machine is None:
            results['manufacturing_link']={'status':'failed','error':'machine plan required'};errors.append('manufacturing_link')
        else:
            linked={'assembly_plan':machine['assembly_plan'],'components':machine['drawing_plan']['bom'],
                    'part_parameters':request['machine'].get('manufacturing',{}).get('part_parameters',{}),
                    'drawing_settings':request['machine'].get('manufacturing',{}).get('drawing_settings',{})}
            mismatch=[k for k,v in linked.items() if k in platform and review_digest(platform[k])!=review_digest(v)]
            if mismatch:
                results['manufacturing_link']={'status':'failed','error':'manufacturing inputs conflict with machine output','fields':mismatch};errors.append('manufacturing_link')
            else:
                platform.update(linked)
                results['manufacturing_link']={'status':'review_required','assembly_plan_sha256':review_digest(linked['assembly_plan']),
                    'bom_sha256':review_digest(linked['components']),'native_references_verified':False}
    if platform:stage('platform',lambda:build_delivery(platform,root/'platform'))
    # Status cannot be upgraded by a generator merely producing files.
    if any(r.get('status') in {'failed','conflict'} for r in results.values()):errors.append('stage_failure')
    pending=[k for k,r in results.items() if r.get('status') in {'pending_mapping','pending_confirmation','review_required','ready_for_native'}]
    repository=Path(__file__).resolve().parents[1]
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=repository,capture_output=True,text=True)
    actual_revision=revision.stdout.strip() if revision.returncode==0 else 'unrecorded_source_archive'
    code={str(p.relative_to(repository)):hashlib.sha256(p.read_bytes()).hexdigest()
          for folder in ('src','work','feature_tree','geometry_ir') for p in sorted((repository/folder).rglob('*.py'))}
    code['app.py']=hashlib.sha256((repository/'app.py').read_bytes()).hexdigest()
    report={'schema_version':1,'status':'failed' if errors else 'review_required',
        'stages':results,'errors':sorted(set(errors)),'pending_stages':pending,
        'request_sha256':review_digest(request),'cad_executed':False,'manufacturing_approved':False,
        'native_acceptance':'pending_windows_validation','source_revision':actual_revision,'declared_source_revision':request.get('source_revision')}
    for name,value in [('request.json',request),('release-result.json',report)]:
        (root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
    (root/'HANDOFF.json').write_text(json.dumps({'schema_version':1,'files':files,'request_sha256':review_digest(request),
          'source_revision':report['source_revision'],'code_sha256':code,'native_acceptance':'not_run','original_files_modified':False},indent=2),encoding='utf-8')
    with zipfile.ZipFile(root/'gork-unified.zip','x',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.name!='gork-unified.zip':archive.write(path,str(path.relative_to(root)))
    return report
