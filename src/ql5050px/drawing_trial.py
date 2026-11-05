"""Explicit incomplete-model drawing trial. Production admission stays unchanged."""
import hashlib,json,traceback
from pathlib import Path
from .native_machine import read_member
from ..a01_next.native_production import A01ProductionDriver


def require_no_running_solidworks(inventory=None):
    """Fail closed before this spawn-only drawing route creates another CAD PID."""
    if inventory is None:
        def inventory():
            import win32com.client
            service=win32com.client.GetObject('winmgmts:')
            return [int(process.ProcessId) for process in service.ExecQuery(
                "SELECT ProcessId FROM Win32_Process WHERE Name='SLDWORKS.exe'")]
    try:
        pids=list(inventory())
        if any(type(pid) is not int or pid<=0 for pid in pids):raise ValueError('invalid process inventory')
    except Exception as error:
        raise RuntimeError('无法核实 SolidWorks 进程，未启动新实例：'+str(error)) from error
    if pids:raise RuntimeError('已有 SolidWorks 实例（PID '+','.join(map(str,pids))+'）。请先保存并关闭；本次未启动第二个实例。')
    return {'running_pids':[],'checked':True}


class TrialDriver(A01ProductionDriver):
    partial_model_test=True
    def __init__(self,lease,root,models,report):
        super().__init__(lease,root);self.models=Path(models).resolve();self.report=report

    def require_isolated_model(self,path):
        if not Path(path).resolve().is_relative_to(self.models):raise ValueError('trial source must be in isolated models directory')

    def open_document(self,path,configuration='',readonly=False):
        from sw_compat.model_document import model_document
        from solidworks_generator import _as_interface,ensure_solidworks_typelib
        path=Path(path).resolve()
        if not path.is_relative_to(self.models) and not path.is_relative_to(self.root):raise ValueError('external file refused')
        app=self.guard();kind={'.sldprt':1,'.sldasm':2,'.slddrw':3}[path.suffix.lower()]
        result=app.OpenDoc6(str(path),kind,3,configuration,0,0)
        raw=result[0] if isinstance(result,tuple) else result
        code=result[1] if isinstance(result,tuple) else 0
        self.report.setdefault('loads',[]).append({'path':str(path),'error':code,'readonly':True})
        if raw is None:raise RuntimeError('OpenDoc6 returned no document')
        model=model_document(raw)
        if Path(str(read_member(model,'GetPathName'))).resolve()!=path:raise RuntimeError('wrong document returned')
        self.lease.note_owned_document(str(read_member(model,'GetTitle')),id(model))
        if kind==2:
            assembly=_as_interface(ensure_solidworks_typelib(),model,'IAssemblyDoc')
            rows=[]
            for c in assembly.GetComponents(False) or []:
                p=str(read_member(c,'GetPathName'));exists=bool(p) and Path(p).is_file()
                if exists and not Path(p).resolve().is_relative_to(self.models):raise RuntimeError('existing external model reference refused')
                rows.append({'name':read_member(c,'Name2'),'path':p,'exists':exists})
            self.report['components']=rows
        current=read_member(app,'GetFirstDocument')
        while current is not None:
            doc=model_document(current);title=str(read_member(doc,'GetTitle'));filename=str(read_member(doc,'GetPathName'))
            if title not in self.lease.owned_docs:
                if not filename or not Path(filename).resolve().is_relative_to(self.models):raise RuntimeError('unexpected document appeared; preserve session')
                self.lease.note_owned_document(title,id(doc))
            current=read_member(doc,'GetNext')
        if code not in (0,2):raise RuntimeError('unsupported native load error '+str(code))
        return model


def validate_trial_case(case):
    if not isinstance(case,dict) or case.get('sheet') not in {'A2','A3'}:
        raise ValueError('select A2 or A3 explicitly')
    denominator=case.get('denominator')
    if type(denominator) is not int or denominator not in (2,5,10,20):
        raise ValueError('select scale 1:2, 1:5, 1:10 or 1:20 explicitly')
    return {'sheet':case['sheet'],'denominator':denominator}


def verify_part_size(bounds,expected,source_sha256):
    """Model-space readback only; drawing outlines are never part dimensions."""
    import math
    if len(bounds)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds):
        raise ValueError('finite six-coordinate model bounds required')
    sizes=[bounds[i+3]-bounds[i] for i in range(3)]
    if any(v<=0 for v in sizes):raise ValueError('positive source model extents required')
    result={'size_mm':sizes,'bounds_mm':list(bounds),'source_sha256':source_sha256,
            'precision':'approximate_model_bounds','manufacturing_approved':False}
    if expected is not None:
        if not isinstance(expected,dict) or expected.get('source_sha256')!=source_sha256:
            raise ValueError('model expectation is not bound to these source bytes')
        wanted=expected.get('size_mm');tolerance=expected.get('tolerance_mm',.01)
        if (not isinstance(wanted,(list,tuple)) or len(wanted)!=3
                or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in wanted)
                or type(tolerance) not in (int,float) or not math.isfinite(tolerance) or not 0<tolerance<=.1):
            raise ValueError('explicit positive expected extents and bounded tolerance required')
        if any(not math.isclose(a,b,rel_tol=0,abs_tol=tolerance) for a,b in zip(sizes,wanted)):
            raise RuntimeError('source model dimensions differ from the reviewed test sample')
        result['expected_size_verified']=True
    return result


def verify_reusable_trial_session(row,pids,documents,*,process_probe):
    """Only a completed receipt's exact idle test instance can be reused."""
    if row.get('status')!='COMPLETED' or row.get('session_state')!='RESOLVED':
        raise RuntimeError('only a completed resolved test session may be reused')
    metadata=row.get('metadata') or {}
    if isinstance(metadata,str):metadata=json.loads(metadata)
    identity=metadata.get('process');controller=metadata.get('controller')
    if not isinstance(identity,dict) or pids!=[identity.get('pid')]:
        raise RuntimeError('unknown or multiple SolidWorks instances; no reuse')
    if process_probe(controller) or not process_probe(identity):
        raise RuntimeError('prior controller is active or test process identity changed')
    if documents:raise RuntimeError('existing documents present; no reuse or close')
    return identity


def trial_task(case,template,configuration,bom_template,*,model_kind):
    """Part views never claim an assembly BOM; both routes require PDF proof."""
    if model_kind not in (1,2):raise ValueError('trial requires a part or assembly model')
    case=validate_trial_case(case)
    w,h={'A2':(594,420),'A3':(420,297)}[case['sheet']]
    tag=case['sheet']+'-1-'+str(case['denominator'])
    return dict(id=tag,node='machine',filename=tag+'-TRIAL.SLDDRW',template=template,
        width_mm=w,height_mm=h,scale=[1,case['denominator']],projection='first_angle',
        configuration=configuration,auto_layout=True,center_views=True,dimensions=[],
        annotations=[{'text':'TEST ONLY - NOT FOR PRODUCTION','position_mm':[30,h-40]}],
        balloons=[],exports=['SLDDRW','PDF'],bom_type='top_level',bom_template=bom_template,
        drawing_model={'views':[dict(id=k,kind='model',orientation=o,position_mm=[100,100])
            for k,o in [('front','*Front'),('top','*Top'),('right','*Right')]],
            'bom':[{'scope':'available_top_level_only'}] if model_kind==2 else []})


def run_trial(request):
    if request.get('explicit_partial_model_test') is not True:raise ValueError('explicit trial-mode confirmation required')
    cases=request.get('cases')
    if not isinstance(cases,list) or not cases:raise ValueError('at least one explicit drawing case required')
    for case in cases:validate_trial_case(case)
    if len({(case['sheet'],case['denominator']) for case in cases})!=len(cases):raise ValueError('duplicate drawing cases')
    from sw_session import run_on_task_sta,current_lease
    from sw_owned_launch import owned_solidworks
    root=Path(request['output']).resolve()
    models=Path(request['models']).resolve();assembly=Path(request['assembly']).resolve()
    if not assembly.is_relative_to(models):raise ValueError('assembly outside isolated model root')
    import_dimensions=request.get('import_model_dimensions',False)
    if type(import_dimensions) is not bool:raise ValueError('model dimension import must be explicit boolean')
    if import_dimensions:
        if assembly.suffix.lower()!='.sldprt':raise ValueError('model dimension import pilot supports standalone parts only')
        from .model_dimensions import validate_required_parameters
        validate_required_parameters(request.get('required_model_dimensions'))
    elif request.get('required_model_dimensions'):
        raise ValueError('required model dimensions cannot be ignored; enable explicit import')
    deduplicate=request.get('deduplicate_model_dimensions',False)
    preferences=request.get('dimension_view_preferences',{})
    if type(deduplicate) is not bool or (deduplicate and not import_dimensions):
        raise ValueError('dimension deduplication requires explicit model dimension import')
    correlate_pdf=request.get('correlate_model_dimensions_pdf',False)
    if type(correlate_pdf) is not bool or (correlate_pdf and not import_dimensions):
        raise ValueError('PDF dimension correlation requires explicit model dimension import')
    if not isinstance(preferences,dict) or any(key not in request.get('required_model_dimensions',[]) or value not in {'front','top','right'} for key,value in preferences.items()):
        raise ValueError('view preferences must refer to required model dimensions and named standard views')
    originals={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in models.rglob('*') if p.is_file() and not p.name.startswith('~$')}
    report={'mode':'explicit_partial_model_test','manufacturing_approved':False,'status':'running','cells':[],
            'acceptance_state':'reviewing','delivery_accepted':False}
    created_output=False
    def checkpoint():
        from drawing_review import atomic_json
        atomic_json(root/'result.json',report)
        from app_logging import get_journal
        get_journal().record('native_drawing_checkpoint',output=str(root),status=report['status'],cells=[{'tag':c['tag'],'status':c['status']} for c in report['cells']])
    def job():
        nonlocal created_output
        root.mkdir(parents=True,exist_ok=False)
        created_output=True
        binding=None
        try:
            reuse=request.get('reuse_session_from_receipt')
            if reuse:
                from cad_receipts import ReceiptStore
                from cad_reconcile import process_still_matches
                from sw_owned_launch import _snapshot_sldworks_pids,_discover_attached,_read_pid
                row=ReceiptStore(request.get('state_db')).get(reuse)
                pids=_snapshot_sldworks_pids()
                # Validate receipt and PID before touching a COM application.
                identity=verify_reusable_trial_session(row,pids,[],process_probe=process_still_matches)
                app=_discover_attached(identity['pid'])
                if app is None or _read_pid(app)!=identity['pid']:raise RuntimeError('exact test instance unavailable')
                verify_reusable_trial_session(row,pids,read_member(app,'GetDocuments') or [],process_probe=process_still_matches)
                app=None
                report['launch_preflight']={'reuse_verified_pid':identity['pid'],'documents':[],'checked':True}
            else:report['launch_preflight']=require_no_running_solidworks()
            checkpoint()
            from sw_owned_launch import attached_solidworks
            session=attached_solidworks if reuse else owned_solidworks
            with session(Path(request['sw_exe'])) as binding:
                from drawing_run import note_drawing_process
                note_drawing_process(current_lease())
                driver=TrialDriver(current_lease(),root,models,report)
                source=driver.open_document(assembly,readonly=True)
                config=str(source.ConfigurationManager.ActiveConfiguration.Name)
                model_kind=int(read_member(source,'GetType'))
                report['source_model_kind']='part' if model_kind==1 else 'assembly' if model_kind==2 else 'unsupported'
                if model_kind==1:
                    import solidworks_generator as sw
                    from part_verification import solid_inventory
                    bounds,_=solid_inventory(sw._as_interface(sw.ensure_solidworks_typelib(),source,'IPartDoc'),sw,sw.ensure_solidworks_typelib())
                    report['source_geometry']=verify_part_size(bounds,request.get('expected_part_geometry'),originals[str(assembly)])
                for case in request['cases']:
                    tag=case['sheet']+'-1-'+str(case['denominator']);cell={'tag':tag,'status':'running'};report['cells'].append(cell);checkpoint()
                    task=trial_task(case,request['templates'][case['sheet']],config,request['bom_template'],model_kind=model_kind)
                    if import_dimensions:task.update(import_model_dimensions=True,required_model_dimensions=request['required_model_dimensions'],
                        deduplicate_model_dimensions=deduplicate,dimension_view_preferences=preferences,
                        correlate_model_dimensions_pdf=correlate_pdf)
                    try:
                        cell['drawing']=driver.export_manufacturing({'status':'ready_for_native','tasks':[task]},{'documents':{'machine':{'path':str(assembly),'configuration':config}}},root/tag)
                        cell['status']='pass_pending_visual'
                        if import_dimensions:
                            from drawing_review import DrawingEvidence
                            evidence=DrawingEvidence.load(cell['drawing']['results'][0]['drawing_evidence'])
                            cell['model_dimension_import']=evidence.data.get('model_dimension_import')
                            cell['dimension_deduplication']=evidence.data.get('dimension_deduplication')
                            cell['pdf_dimension_correlation']=evidence.data.get('pdf_dimension_correlation')
                            if not evidence.data['complete']:
                                cell['status']='pdf_dimensions_pending' if correlate_pdf and evidence.data.get('pdf_dimension_correlation',{}).get('status')!='verified' else 'dimensions_pending'
                        cell.update(acceptance_state='reviewing',delivery_accepted=False)
                    except (ValueError,RuntimeError) as error:
                        message=str(error);cell.update(error=message,status='failed')
                        if hasattr(error,'diagnostic'):
                            cell['layout_diagnostic']=error.diagnostic
                            cell['explicit_fit_alternatives']=error.alternatives
                        if 'layout_does_not_fit' not in message and 'layout_title_block_conflict' not in message:raise
                        cell['status']='expected_layout_block'
                        from sw_compat.model_document import model_document
                        doc=model_document(read_member(driver.app,'ActiveDoc'))
                        if int(read_member(doc,'GetType'))!=3:raise RuntimeError('blocked diagnostic is not a drawing')
                        cell['diagnostic']=driver.save_reopen(doc,root/(tag+'-BLOCKED-DIAGNOSTIC.SLDDRW'),'')
                    checkpoint()
                report['case_summary']={state:sum(cell['status']==state for cell in report['cells'])
                    for state in ('pass_pending_visual','expected_layout_block','dimensions_pending','pdf_dimensions_pending','failed')}
                report['status']='completed_partial_model_trial'
        finally:
            if binding:report['session']=binding.evidence()
            checkpoint()
        report['source_hash_mismatches']=[p for p,h in originals.items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
        report['output']=str(root)
        return report
    try:
        from drawing_run import run_receipted_drawing
        payload={k:v for k,v in request.items() if k not in {'output','idempotency_key','state_db'}}
        templates={str(Path(p).resolve()):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in
                   {request['templates'][case['sheet']] for case in request['cases']}|{request['bom_template']}}
        returned=run_receipted_drawing(assembly,originals,{'entry':'drawing_trial','request':payload,'template_sha256':templates},job,
            timeout=1800,task_name='one-click-drawing-trial',state_db=request.get('state_db'),key=request.get('idempotency_key'))
        if returned.get('request_receipt',{}).get('replayed'):return returned
        report.update(returned)
    except Exception as error:
        from app_logging import get_journal
        get_journal().exception('native_drawing_failed',error,hresult=getattr(error,'hresult',None))
        report.update(status='failed',error=str(error),traceback=traceback.format_exc())
    report['source_hash_mismatches']=[p for p,h in originals.items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
    if created_output:checkpoint()
    return report
