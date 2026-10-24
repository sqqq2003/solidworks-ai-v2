"""One owned transaction: assembly -> linked drive variant -> checks -> drawings."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
import zipfile


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,ensure_ascii=False).encode()).hexdigest()


def plan_production(config):
    from .machine_package import plan_machine
    machine=plan_machine(config)
    links=deepcopy(config.get('production_links',{}))
    catalog=machine['assembly_plan']['tree']['catalog']
    pending=list(machine['oem_mapping_required'])
    root=machine['assembly_plan']['tree']['root']
    for component in machine['drive_plan']['component_modifications']:
        node=links.get('components',{}).get(component['component'])
        if node not in catalog:pending.append({'module':'production','component':component['component'],'field':'production_links.components'})
        elif component['configuration']!=catalog[node]['configuration']:
            raise ValueError('drive/assembly configuration differs for '+node)
    for mate in machine['drive_plan']['affected_mates']:
        node=links.get('mates',{}).get(mate.get('id'))
        if node not in catalog or catalog[node]['type']!='assembly':
            pending.append({'module':'production','mate':mate.get('id'),'field':'production_links.mates'})
        elif mate['configuration']!=catalog[node]['configuration']:
            raise ValueError('mate/assembly configuration differs for '+node)
    if machine['drive_plan'].get('assembly_configuration')!=catalog[root].get('configuration'):
        pending.append({'module':'production','field':'root_configuration_match'})
    payload={'schema_version':1,'machine':'QL-5050PX','machine_plan':machine,'links':links,
        'motion_samples':deepcopy(config.get('motion_samples',[])),
        'pending_mapping':pending,'status':'conflict' if machine['status']=='conflict' else ('pending_mapping' if pending else 'ready_for_native'),
        'cad_executed':False,'native_acceptance':'pending_windows_validation','manufacturing_approved':False}
    payload['review_sha256']=fingerprint(payload)
    return payload


def write_production_package(config,destination):
    from .drawing_bom import export_bom_csv
    plan=plan_production(config)
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    for name,data in [('production-plan.json',plan),('pending-mapping.json',plan['pending_mapping']),
                      ('windows-matrix.json',[{'stage':s,'status':'not_run'} for s in ('assembly','drive','checks','drawings','process_exit')])]:
        (root/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    export_bom_csv(plan['machine_plan']['drawing_plan']['bom'],root/'bom.csv')
    manifest={'review_sha256':plan['review_sha256'],'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()},
              'native_acceptance':'pending_windows_validation','manufacturing_approved':False}
    (root/'HANDOFF.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    with zipfile.ZipFile(root/'gork-production.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.iterdir()):
            if p.suffix!='.zip':z.write(p,p.name)
    return {'status':plan['status'],'plan':plan,'package':str(root/'gork-production.zip'),'cad_executed':False}


def validate_review(plan,review_sha256):
    payload=deepcopy(plan);declared=payload.pop('review_sha256',None)
    if declared!=review_sha256 or fingerprint(payload)!=review_sha256:
        raise ValueError('review hash does not match production plan')
    if plan['status']!='ready_for_native' or plan['pending_mapping']:
        raise ValueError('production refuses incomplete OEM mapping or conflicts')
    machine=plan['machine_plan']
    for key in ('assembly_plan','drive_plan','drawing_plan'):
        stage=machine[key]
        if stage['status']!='ready_for_native' or stage.get('pending_mapping') or stage.get('conflicts'):
            raise ValueError('production stage is not ready: '+key)


def execute_production(plan,driver,destination,*,review_sha256):
    """Driver must be inside an owned guarded session. No COM attachment here.

    Fatal stage failure preserves checkpoint and stops dependent exports. No retry
    or cleanup success is inferred; the existing supervisor owns process lifetime.
    """
    validate_review(plan,review_sha256)
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    report={'schema_version':1,'review_sha256':review_sha256,'status':'running','stages':[],
        'cad_executed':False,'native_acceptance':'pending_windows_validation','manufacturing_approved':False}
    def checkpoint():
        temporary=root/'checkpoint.tmp'
        with temporary.open('w',encoding='utf-8') as f:
            json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        temporary.replace(root/'checkpoint.json')
    def stage(name,call):
        report['stages'].append({'name':name,'status':'running','started':time.time()});checkpoint()
        result=call();report['stages'][-1].update(status='returned',result=result);checkpoint();return result
    machine=plan['machine_plan'];tree=machine['assembly_plan']['tree'];root_node=tree['root']
    try:
        assembly=stage('assembly',lambda:driver.build_assembly(machine['assembly_plan'],root/'assembly'))
        report['cad_executed']=True
        documents=deepcopy(assembly['documents'])
        drive=deepcopy(machine['drive_plan'])
        drive['source_assembly']=documents[root_node]['path']
        for component in drive['component_modifications']:
            component['document']=documents[plan['links']['components'][component['component']]]['path']
        for mate in drive['affected_mates']:
            mate['document']=documents[plan['links']['mates'][mate['id']]]['path']
        variant=stage('drive',lambda:driver.apply_drive(drive,root/'drive'))
        copies=variant['isolated_documents']
        for node,document in documents.items():
            old=str(Path(document['path']).resolve())
            if old not in copies:raise RuntimeError('variant missing assembly dependency: '+node)
            document['path']=copies[old]
            if not Path(document['path']).resolve().is_relative_to(root):raise ValueError('variant path escaped transaction')
        if not Path(variant['document']['path']).resolve().is_relative_to(root):raise ValueError('variant root escaped transaction')
        documents[root_node]=variant['document']
        checks=stage('checks',lambda:driver.inspect_native(documents[root_node]['path'],plan['motion_samples']))
        if checks.get('simulated_only') is not False:raise ValueError('native checks returned no explicit native evidence')
        # Preserve evidence; no automatic mechanical or manufacturing approval.
        report['mechanical_findings']=checks
        drawings=stage('drawings',lambda:driver.export_manufacturing(machine['drawing_plan'],{'documents':documents},root/'drawings'))
        from .drawing_bom import export_bom_csv
        export_bom_csv(machine['drawing_plan']['bom'],root/'bom.csv')
        report.update(status='outputs_created_review_required',documents=documents,drawings=drawings)
        artifacts={}
        for p in root.rglob('*'):
            if p.is_file() and p.suffix.lower() in {'.sldasm','.sldprt','.slddrw','.dxf','.csv'}:
                if p.is_symlink() or not p.resolve().is_relative_to(root):raise ValueError('external output artifact')
                artifacts[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
        report['artifact_sha256']=artifacts;checkpoint();return report
    except Exception as exc:
        report.update(status='failed',error=type(exc).__name__+': '+str(exc))
        if report['stages'] and report['stages'][-1]['status']=='running':report['stages'][-1]['status']='failed'
        checkpoint();raise
