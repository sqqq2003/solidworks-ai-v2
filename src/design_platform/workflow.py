"""One offline integration/handoff entrypoint; per-module failures are retained."""
from pathlib import Path
from copy import deepcopy
import json,zipfile
from design_review import analyze_impact,evaluate_acceptance,propose_repairs
from design_review.impact import review_digest
from .mapping import suggest_bindings,approve_binding
from .calculations import compute
from .catalogue import select_parts,selected_bom_rows
from .templates import instantiate,module_diff
from .manufacturing import export_manufacturing
from .rules import evaluate_rules
from .projects import file_hash


def build_delivery(request,destination):
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    result={'schema_version':1,'status':'review_required','modules':{},'errors':[],
        'cad_executed':False,'manufacturing_approved':False,'native_acceptance':'pending_windows_validation'}
    def run(name,call):
        try:value=call()
        except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
            value={'status':'failed','error':type(exc).__name__+': '+str(exc)};result['errors'].append({'module':name,**value})
        result['modules'][name]=value;return value
    if 'instruction' in request:
        from .assistant import parse_request
        run('instruction',lambda:parse_request(request['instruction']))
    if 'knowledge_lookup' in request:
        from .knowledge import search_cases
        lookup=request['knowledge_lookup']
        run('knowledge',lambda:search_cases(lookup['database'],lookup['query'],lookup['context']))
    if 'project_store' in request:
        from .projects import history
        run('project_history',lambda:history(request['project_store']))
    intentions=deepcopy(request.get('intentions',{}))
    if 'snapshot' in request:
        mapping=run('mapping',lambda:suggest_bindings(request['snapshot'],request.get('parameters',[])))
        if 'mappings' in mapping:
            bindings=run('bindings',lambda:[approve_binding(mapping,row.get('approval_record',row)) for row in request.get('binding_approvals',[])])
            if isinstance(bindings,list):
                for row in bindings:
                    intentions.setdefault('parameters',{})[row['parameter']]={key:row.get(key) for key in ('role','unit','allowed_range','review_status','source')}
    if 'plan' in request and 'intentions' in request:run('impact',lambda:analyze_impact(request['plan'],intentions))
    run('mechanical_rules',lambda:evaluate_rules(request.get('values',{}),request.get('rules',[])))
    run('calculations',lambda:[compute(row['kind'],row['inputs']) for row in request.get('calculations',[])])
    components=list(request.get('components',[]))
    if 'catalogue' in request:
        run('catalogue',lambda:[select_parts(request['catalogue'],row['category'],row['requirements']) for row in request.get('selection_requirements',[])])
        selected=run('selected_parts',lambda:selected_bom_rows(request['catalogue'],request.get('selections',[])))
        if isinstance(selected,list):components+=selected
    if 'template' in request:run('template',lambda:instantiate(request['template'],request.get('template_values',{})))
    if 'previous_configuration' in request:run('configuration_diff',lambda:module_diff(request['previous_configuration'],request.get('configuration',{})))
    run('manufacturing',lambda:export_manufacturing(components,request.get('manufacturing_register',[]),request.get('revision','DEVELOPMENT'),root/'manufacturing',
        assembly_plan=request.get('assembly_plan'),part_parameters=request.get('part_parameters'),settings=request.get('drawing_settings')))
    if 'acceptance' in request:
        assessment=run('acceptance',lambda:evaluate_acceptance(request['acceptance'],artifact_root=request.get('artifact_root')))
        if 'checks' in assessment:run('repair_proposals',lambda:propose_repairs(assessment))
    result['status']='failed' if result['errors'] or any(isinstance(value,dict) and value.get('status')=='failed' for value in result['modules'].values()) else 'review_required'
    matrix=json.loads((Path(__file__).resolve().parents[2]/'delivery/design-platform/windows-matrix.json').read_text(encoding='utf-8'))
    for name,data in [('request.json',request),('platform-result.json',result),('windows-matrix.json',matrix)]:
        (root/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    modules=root/'modules';modules.mkdir()
    for name,data in result['modules'].items():
        (modules/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    files={str(p.relative_to(root)):file_hash(p) for p in root.rglob('*') if p.is_file()}
    source=Path(__file__).resolve().parent
    code={str(p.relative_to(source.parent)):file_hash(p) for folder in (source,source.parent/'design_review') for p in sorted(folder.glob('*.py'))}
    handoff={'schema_version':1,'request_sha256':review_digest(request),'source_revision':request.get('source_revision','unrecorded; pin Git SHA for native handoff'),'code_sha256':code,'files':files,'test_status':'not_run_except_syntax_import_and_example_smoke',
        'native_acceptance':'pending_windows_validation','binary_cad_included':False}
    (root/'HANDOFF.json').write_text(json.dumps(handoff,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=root/'gork-platform-batch.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.rglob('*')):
            if p.is_file() and p!=archive:z.write(p,str(p.relative_to(root)))
    return {'status':result['status'],'package':str(archive),'errors':result['errors'],'modules':list(result['modules']),
        'cad_executed':False,'test_status':'not_run_except_syntax_import_and_example_smoke'}
