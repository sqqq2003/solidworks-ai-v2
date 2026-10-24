"""A01 mapped work-copy workflow. No CAD is started by planning or import."""
from pathlib import Path
import hashlib
import math
from ..sw_api.mapping import load_mappings
from .stable_references import validate_references


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_request(request):
    if not isinstance(request,dict) or request.get('schema_version') != 1:
        raise ValueError('production schema_version 1 required')
    source=Path(request['source_assembly']).resolve()
    if source.suffix.lower()!='.sldasm' or sha(source)!=request.get('source_sha256'):
        raise ValueError('source assembly identity mismatch')
    if not request.get('configuration'):
        raise ValueError('explicit assembly configuration required')
    rows=load_mappings(request['mapping'])
    values=request['values']
    if not rows or set(values)!={r.parameter for r in rows}:
        raise ValueError('exact nonempty confirmed mapping/value set required')
    edits=[]
    for row in rows:
        if row.status!='confirmed' or row.component_kind!='editable' or row.unit not in ('mm','m','deg'):
            raise ValueError(row.parameter+': confirmed editable length/angle mapping required')
        path=Path(row.document).resolve()
        if '@' not in row.dimension or row.dimension.split('@')[1]!=row.feature:
            raise ValueError(row.parameter+': dimension must identify the mapped feature')
        if sha(path)!=request['document_sha256'].get(str(path)):
            raise ValueError(row.parameter+': mapped document identity mismatch')
        value=values[row.parameter]
        if type(value) not in (int,float) or not math.isfinite(value) or not row.allowed_range[0]<=value<=row.allowed_range[1]:
            raise ValueError(row.parameter+': out-of-range/nonfinite value')
        edits.append(dict(parameter=row.parameter,document=str(path),configuration=row.configuration,
            feature=row.feature,dimension=row.dimension,unit=row.unit,value=value))
    mates=request.get('mates',[])
    refs=request.get('references',{'schema_version':1,'references':[]})
    if mates:
        validate_references(refs)
        registry={r['id']:r for r in refs['references']}
        seen=set()
        for mate in mates:
            if not mate.get('id') or mate['id'] in seen or mate.get('type') not in ('coincident','concentric','parallel','distance','angle'):
                raise ValueError('unique supported mate id required')
            seen.add(mate['id'])
            if len(mate.get('references',[]))!=2 or len(set(mate['references']))!=2 or any(x not in registry for x in mate['references']):
                raise ValueError('two distinct registered references required')
            if any(registry[x]['document_sha256']!=request['source_sha256'] or registry[x]['configuration']!=request['configuration'] for x in mate['references']):
                raise ValueError('mate tokens must be captured in source assembly/configuration context')
            if type(mate.get('alignment')) is not int or mate['alignment'] not in (0,1,2):
                raise ValueError('explicit mate alignment 0/1/2 required')
            key={'distance':'distance_mm','angle':'angle_deg'}.get(mate['type'])
            if key and (type(mate.get(key)) not in (int,float) or not math.isfinite(mate[key])):
                raise ValueError('explicit finite '+key+' required')
    drawings=request.get('drawing_plan')
    if drawings:
        if drawings.get('status')!='ready_for_native' or not drawings.get('tasks'):
            raise ValueError('confirmed manufacturing drawing plan required')
        names=set()
        for task in drawings['tasks']:
            from ..ql5050px.manufacturing_drawings import safe_name
            filename=task['filename']
            if safe_name(filename)!=filename or not filename.lower().endswith('.slddrw') or filename.casefold() in names:
                raise ValueError('unique safe SLDDRW filename required')
            names.add(filename.casefold())
            if task['node']!='A01' or task['exports']!=['SLDDRW']:
                raise ValueError('A01 assembly drawing supports SLDDRW only in this entry')
            if task.get('projection')!='first_angle' or task.get('standard')!='GB_T':
                raise ValueError('explicit GB_T first_angle required')
            if task.get('configuration')!=request['configuration']:
                raise ValueError('drawing configuration must match mapped assembly configuration')
            if not task.get('dimensions') or not task.get('drawing_model',{}).get('bom'):
                raise ValueError('production assembly drawing needs mapped dimensions and linked BOM')
            if any(not task.get(key) for key in ('process','datum_scheme','tolerance_scheme')):
                raise ValueError('confirmed process/datum/tolerance scheme required')
            if any(d.get('status')!='confirmed' or not d.get('references') for d in task['dimensions']):
                raise ValueError('drawing dimension references must be confirmed')
            if not Path(task['template']).is_file() or not Path(task['bom_template']).is_file():
                raise ValueError('existing drawing/BOM templates required')
    return dict(status='ready_for_native',source_assembly=str(source),configuration=request['configuration'],
                source_sha256=request['source_sha256'],edits=edits,mates=mates,references=refs,
                drawing_plan=drawings,cad_executed=False,engineering_acceptance='unverified')


def execute_request(request,driver,destination):
    # Revalidate source bytes immediately before isolation; never operate originals.
    plan=prepare_request(request)
    root=Path(destination)
    copied=driver.pack_and_go(plan['source_assembly'],root/'refs',plan['configuration'])
    copies=driver.receipt['events'][-1]['copies']
    edits=driver.apply_mapped_dimensions(plan['edits'],copies)
    mate_evidence=driver.apply_persistent_mates(copied,plan['configuration'],plan['mates'],plan['references'])
    checks=driver.inspect_native(copied)
    if checks.get('interference_count',0):
        raise RuntimeError('assembly interference candidates require review before drawings')
    drawings=None
    if plan['drawing_plan']:
        receipt={'documents':{'A01':{'path':copied,'configuration':plan['configuration']}}}
        drawings=driver.export_manufacturing(plan['drawing_plan'],receipt,root/'drawings')
    return dict(status='native_workflow_executed_pending_review',cad_executed=True,
                document=copied,dimension_readback=edits,mates=mate_evidence,checks=checks,
                drawings=drawings,engineering_acceptance='unverified',
                cad_release_approved=False,pdf_layout_review='not_implemented_in_this_entry')
