"""scan -> classify -> map -> plan -> calculate -> export, entirely offline."""
import hashlib,json,zipfile
from pathlib import Path
from .intelligent_scan import scan_snapshot
from .automatic_mapping import map_parameters,confirmed_targets
from .intelligent_decision import decide
from .mechanical_selection import calculate,select_catalogue


def run_intelligence(request, output_dir=None):
    database=scan_snapshot(request['snapshot'],request.get('previous_database'))
    report=map_parameters(database,request.get('pending_parameters',['length','width','height','conveyor_height','center_distance','stroke']))
    for approved in confirmed_targets(report,request.get('approvals',[])):
        row=next(r for r in report['mappings'] if r['parameter']==approved['parameter'])
        for candidate in row['candidates']:
            if candidate['document_id']==approved['document_id'] and candidate['dimension']==approved['dimension']: candidate.update(approved)
    decision=decide(database,report,request.get('target',{'length':1800,'width':900,'height':1500}),request.get('rules',{}))
    calculations=[calculate(item['kind'],item.get('inputs',{})) for item in request.get('calculations',[])]
    selection=select_catalogue(request['catalogue'],request.get('requirements',[])) if request.get('catalogue') else {'status':'pending_catalogue'}
    result={'machine':'QL-5050PX','status':'pending_mapping','database':database,'mapping_report':report,
            'decision_plan':decision,'calculations':calculations,'selection':selection,'cad_executed':False,
            'mechanical_acceptance':'unverified','test_status':'not_run','plan':{'parameter_register':{},'values_mm':{}}}
    if output_dir:
        root=Path(output_dir);root.mkdir(parents=True,exist_ok=False)
        files={'structure-database':database,'parameter-mappings':report,'variant-decisions':decision,
               'mechanical-calculations':calculations,'catalogue-selection':selection,'intelligence-result':result,
               'test-matrix':[{'case':name,'status':'not_run'} for name in ('native-readonly-scan','incremental-dedup','classification-ambiguity','mapping-conflicts','protected-components','mechanical-units','catalogue-boundaries','CLI-desktop-integration')]}
        for name,data in files.items(): (root/(name+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
        manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
        (root/'SHA256.json').write_text(json.dumps(manifest,indent=2))
        with zipfile.ZipFile(root/'gork-intelligence.zip','x',zipfile.ZIP_DEFLATED) as z:
            for p in root.glob('*.json'): z.write(p,p.name)
        result['output_dir']=str(root)
    return result
