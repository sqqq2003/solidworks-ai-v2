"""One offline plan/mapping/test package; no generated or source CAD included."""
import json,hashlib,zipfile
from pathlib import Path
from .planning import plan_variant


def export_package(request,destination):
    plan=plan_variant(request);root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    matrix=[{'case':case,'status':'not_run'} for case in ('source_isolation','native_dimension_mapping','total_including_two_shafts_800mm',
        'protected_shaft_shoulders_bearing_and_drive_interfaces','feature_tree_preserved','mates_and_static_interference',
        'save_close_reopen_readback','source_hash_unchanged','normal_process_exit')]
    for name,data in [('roller-plan.json',plan),('request.json',request),('pending-mapping.json',plan['pending_mapping']),('windows-matrix.json',matrix)]:
        (root/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    manifest={'schema_version':1,'plan_sha256':plan['plan_sha256'],'native_acceptance':'pending_windows_validation',
        'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}}
    (root/'HANDOFF.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    archive=root/'gork-roller-800.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(root.iterdir()):
            if p!=archive:z.write(p,p.name)
    return {'status':plan['status'],'package':str(archive),'pending_mapping':plan['pending_mapping'],'cad_executed':False}
