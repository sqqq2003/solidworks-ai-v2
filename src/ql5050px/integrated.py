"""Unified offline orchestration; native execution remains explicitly gated."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from .intelligence import run_intelligence
from .machine_package import plan_machine, MATRIX
from .decision_bridge import bridge_decisions


def run_integrated(request, output_dir=None):
    intelligence = run_intelligence(request)
    config = deepcopy(request.get('manufacturing', {}))
    target = intelligence['decision_plan']['target_mm']
    if 'envelope' in config and config['envelope'] != target:
        raise ValueError('manufacturing envelope conflicts with intelligence target')
    config['envelope'] = target
    config, bridge = bridge_decisions(intelligence, config, request.get('execution_bindings'))
    machine = plan_machine(config)
    pending = list(machine['oem_mapping_required'])
    pending.extend(bridge['pending_mapping'])
    pending.extend({'module':'parameters','parameter':name}
                   for name in machine['parameters']['pending_mapping'])
    pending.extend({'module':'intelligence','parameter':row['parameter'],
                    'status':row['status']}
                   for row in intelligence['mapping_report']['mappings']
                   if not any(c.get('review_status') == 'confirmed' for c in row['candidates']))
    pending.extend({'module':'decision',**row}
                   for row in intelligence['decision_plan']['pending_mapping'])
    tasks = {'status':'review_required', 'native_write_allowed':False,
             'reason':'review mappings, decisions and independent native plans before Windows execution',
             'sequence':machine['execution_sequence'],
             'assembly':machine['assembly_plan'], 'drive':machine['drive_plan'],
             'drawings':machine['drawing_plan'],
             'decision_plan':intelligence['decision_plan']}
    tasks['decision_bridge'] = bridge
    result = {'schema_version':1,'machine':'QL-5050PX','action':'integrated',
              'status':'conflict' if machine['status']=='conflict' else 'pending_mapping' if pending else 'review_required',
              'plan':machine['parameters'],'intelligence':intelligence,'machine_plan':machine,
              'pending_mapping':pending,'windows_tasks':tasks,
              'cad_executed':False,'mechanical_acceptance':'unverified','test_status':'not_run'}
    if output_dir is not None:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=False)
        documents = {'request':request,'integrated-result':result,
                     'oem-mapping-required':pending,'windows-tasks':tasks,
                     'decision-bridge':bridge,
                     'test-matrix':[{**row,'status':'not_run'} for row in MATRIX] +
                         [{'id':'INT-01','case':'scan/classify/map/decision/calculation integration','status':'not_run'}]}
        for name, payload in documents.items():
            (root/(name+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        from .drawing_bom import export_bom_csv
        export_bom_csv(machine['drawing_plan']['bom'],root/'bom.csv')
        try:
            revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[2],text=True).strip()
        except (OSError,subprocess.CalledProcessError):
            revision = 'unknown; use source archive manifest'
        manifest = {'source_revision':revision,'native_acceptance':'unverified',
                    'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}
        (root/'HANDOFF.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        with zipfile.ZipFile(root/'gork-integrated.zip','x',zipfile.ZIP_DEFLATED) as bundle:
            for p in sorted(root.iterdir()):
                if p.suffix != '.zip': bundle.write(p,p.name)
        result['output_dir'] = str(root)
    return result
