"""Single offline preparation/export entry for four executable recipe families."""
from pathlib import Path
import hashlib,json,zipfile
from .part_recipes import compile_recipe,simulate_recipe,approval_digest


def prepare_jobs(request,*,sw_exe=None,template=None,sketch_plane=None,review=False):
    rows=[];ids=set()
    for source in request['jobs']:
        name=source['id']
        if not name.isascii() or not name.replace('_','').replace('-','').isalnum() or name in ids:raise ValueError('unique ASCII job ids required')
        ids.add(name)
        job=dict(source);bindings=dict(job.get('bindings',{}))
        if template:bindings['template']=str(Path(template).expanduser().resolve())
        if sketch_plane:bindings['sketch_plane']=sketch_plane
        if review and bindings.get('template'):
            template_path=Path(bindings['template'])
            if not template_path.is_file():raise ValueError('part template missing')
            bindings['template_sha256']=hashlib.sha256(template_path.read_bytes()).hexdigest()
        job['bindings']=bindings
        if sw_exe:job['sw_exe']=str(Path(sw_exe).expanduser().resolve())
        plan=compile_recipe(job['recipe'],bindings)
        job['compiled_plan']=plan
        if review:
            if plan['pending_confirmation']:raise ValueError(name+': '+str(plan['pending_confirmation']))
            if not Path(job.get('sw_exe','')).is_file():raise ValueError('existing SW executable required')
            if plan['backend']=='feature_ir' and not Path(bindings.get('template','')).is_file():raise ValueError('existing part template required')
            job['reviewed_digest']=approval_digest(job['recipe'],bindings)
        rows.append(job)
    return rows


MATRIX=[
 ('GOLDEN','p248 original local patch/source distinction, 4/4, first/retest reopen and DXF separately'),
 ('FEATURES','line/circle/arc, constraints, dimensions, extrude/cut and reviewed feature-data operations'),
 ('RECIPES','plate holes, L bracket, stepped revolved shaft, exactly two sheet bends'),
 ('READBACK','feature names/types, explicit dimensions before save and after reopen'),
 ('SHEET','thickness/R/K/direction, relief selection, bend count, folded/flat states and DXF'),
 ('BATCH','serial workers, immutable input, failure retry, successful hash reuse and changed artifact refusal'),
 ('LIFECYCLE','saved checkpoint vs CloseDoc vs context/worker exit, access violation and timeout'),
 ('SAFETY','no original overwrite, no unknown SW shutdown, stale approval rejection, QL/GT-ZX isolation')]


def export_delivery(request,output_dir):
    root=Path(output_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    jobs=prepare_jobs(request)
    reports=[{'id':j['id'],**simulate_recipe(j['recipe'],j['bindings'])} for j in jobs]
    payloads={'request.json':request,'compiled-jobs.json':{'jobs':jobs},'offline-report.json':reports,
        'windows-matrix.json':[{'id':key,'case':case,'status':'pending_windows_validation'} for key,case in MATRIX],
        'capabilities.json':{'native_direct':['sketch_line','sketch_circle','sketch_arc','extrude','cut'],
            'legacy_recipe':['shaft_revolve','sheet_base_bends_relief_flat'],
            'requires_reviewed_feature_data':['hole_wizard','fillet','chamfer','mirror','pattern','edge_flange'],
            'not_certified':['native_binding_compatibility','manufacturing_approval','COM_crash_fix'],
            'native_acceptance':'pending_windows_validation'}}
    for name,payload in payloads.items():(root/name).write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    manifest={'schema_version':1,'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()},
        'offline_scope':'recipe compilation, not native geometry','tests':'no_full_regression','native_acceptance':'pending_windows_validation'}
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    with zipfile.ZipFile(root/'gork-modeling.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in root.glob('*.json'):z.write(p,p.name)
    return {'status':'review_required','results':reports,'output_dir':str(root),'archive':str(root/'gork-modeling.zip'),
        'cad_executed':False,'plan':{},'native_acceptance':'pending_windows_validation'}

