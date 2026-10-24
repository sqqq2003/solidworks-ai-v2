"""End-to-end planning and a self-contained, checksummed Gork execution package."""
import hashlib
import json
from pathlib import Path
import zipfile

from .assembly_builder import plan_assembly
from .drive_variant import plan_drive
from .manufacturing_drawings import plan_drawings
from .workflow import machine_plan


def plan_machine(config):
    parameters = machine_plan(config)
    assembly = plan_assembly(config.get('assembly_tree'),values_mm=parameters['values_mm'],
                             baseline=config.get('baseline_assembly'))
    drive_spec = dict(config.get('drive',{}))
    nodes = drive_spec.pop('nodes',{})
    # Envelope target inputs are explicit design requirements; OEM-dependent
    # dimensions retain missing values unless supported by sourced nodes.
    inputs = dict(drive_spec.pop('inputs',{}))
    for axis in ('length','width','height'):
        name = 'target_'+axis
        if name in nodes: inputs[name] = parameters['values_mm'][name]
    drive = plan_drive(nodes,inputs=inputs,**drive_spec)
    drawings = plan_drawings(assembly,part_parameters=config.get('part_parameters'),settings=config.get('drawing_settings'))
    oem = ([{'module':'assembly',**row} for row in assembly['pending_mapping']]
           +[{'module':'drive',**row} for row in drive['pending_mapping']]
           +[{'module':'drawings',**row} for row in drawings['pending_mapping']])
    return {'schema_version':1,'machine':'QL-5050PX','parameters':parameters,'assembly_plan':assembly,
            'drive_plan':drive,'drawing_plan':drawings,'oem_mapping_required':oem,
            'status':'conflict' if drive['conflicts'] else ('pending_mapping' if oem else 'ready_for_native'),
            'cad_executed':False,'mechanical_acceptance':'unverified','test_status':'not_run',
            'execution_sequence':['isolate_sources','assembly','drive','native_checks','manufacturing_drawings']}


MATRIX = [
    {'id':'ASM-01','case':'tree/reuse/configuration/placement/mate plan','expected':'cycles rejected; unknown refs pending'},
    {'id':'ASM-02','case':'owned Windows Pack and Go + insertion + save/reopen','expected':'all refs inside work root; occurrence counts match'},
    {'id':'DRV-01','case':'envelope change/ratios/centers/belt/chain','expected':'affected components, missing inputs and conflicts reported'},
    {'id':'DRV-02','case':'purchased/fixed dimensions','expected':'no stretch; only explicitly allowed repositioning'},
    {'id':'DRV-03','case':'native mate dimensions/rebuild/readback/checks','expected':'independent copy; native evidence per step'},
    {'id':'DRW-01','case':'register/material/thickness/process/views','expected':'part + assembly tasks and pending engineering data'},
    {'id':'DRW-02','case':'native projected views/dimensions/notes/BOM/balloons','expected':'linked model dimensions and BOM; no fabricated approval'},
    {'id':'DRW-03','case':'sheet flat view and DXF','expected':'native flat output exists; source unchanged'},
    {'id':'PKG-01','case':'CLI/desktop/batch and ZIP checksums','expected':'same API; no COM offline; hashes match'},
]


def write_machine_package(config,destination,*,source_revision='recorded_in_git_delivery_comment'):
    result = plan_machine(config)
    folder = Path(destination).resolve()
    folder.mkdir(parents=True,exist_ok=False)
    documents = {'request.json':config,'machine-plan.json':result,
        'assembly-plan.json':result['assembly_plan'],'drive-plan.json':result['drive_plan'],
        'drawing-plan.json':result['drawing_plan'],'oem-mapping-required.json':result['oem_mapping_required'],
        'test-matrix.json':[{**row,'status':'not_run'} for row in MATRIX]}
    for name,payload in documents.items():
        with (folder/name).open('x',encoding='utf-8') as stream:
            json.dump(payload,stream,ensure_ascii=False,indent=2,allow_nan=False)
    from .drawing_bom import export_bom_csv
    export_bom_csv(result['drawing_plan']['bom'],folder/'bom.csv')
    with (folder/'READ-FIRST.txt').open('x',encoding='utf-8') as stream:
        stream.write('QL-5050PX Issue #9 unified handoff. All tests NOT RUN.\n'
            'Inputs marked simulation are not OEM data. Complete OEM mapping before native execution.\n'
            'Gork finishes p248 first; then run this entire matrix on isolated working copies.\n'
            'No CAD is included. Inspect docs/issue9-handoff.md for callable Windows entrypoints.\n')
    manifest = {'schema_version':1,'source_revision':source_revision,'test_status':'not_run',
                'native_acceptance':'unverified','files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in folder.iterdir() if p.is_file()}}
    with (folder/'HANDOFF.json').open('x',encoding='utf-8') as stream:
        json.dump(manifest,stream,ensure_ascii=False,indent=2)
    archive = folder/'gork-execution-package.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(folder.iterdir()):
            if path.is_file() and path!=archive: bundle.write(path,path.name)
    return {'status':result['status'],'package_dir':str(folder),'archive':str(archive),
            'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'pending_count':len(result['oem_mapping_required']),'test_status':'not_run','plan':result}
