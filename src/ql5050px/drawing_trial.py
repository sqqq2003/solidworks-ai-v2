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


def trial_task(case,template,configuration,bom_template,*,model_kind):
    """Part views never claim an assembly BOM; both routes require PDF proof."""
    if model_kind not in (1,2):raise ValueError('trial requires a part or assembly model')
    w,h={'A2':(594,420),'A3':(420,297)}[case['sheet']]
    tag=case['sheet']+'-1-'+str(case['denominator'])
    return dict(id=tag,node='machine',filename=tag+'-TRIAL.SLDDRW',template=template,
        width_mm=w,height_mm=h,scale=[1,case['denominator']],projection='first_angle',
        configuration=configuration,auto_layout=True,dimensions=[],
        annotations=[{'text':'TEST ONLY - NOT FOR PRODUCTION','position_mm':[30,h-40]}],
        balloons=[],exports=['SLDDRW','PDF'],bom_type='top_level',bom_template=bom_template,
        drawing_model={'views':[dict(id=k,kind='model',orientation=o,position_mm=[100,100])
            for k,o in [('front','*Front'),('top','*Top'),('right','*Right')]],
            'bom':[{'scope':'available_top_level_only'}] if model_kind==2 else []})


def run_trial(request):
    if request.get('explicit_partial_model_test') is not True:raise ValueError('explicit trial-mode confirmation required')
    from sw_session import run_on_task_sta,current_lease
    from sw_owned_launch import owned_solidworks
    root=Path(request['output']).resolve()
    models=Path(request['models']).resolve();assembly=Path(request['assembly']).resolve()
    if not assembly.is_relative_to(models):raise ValueError('assembly outside isolated model root')
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
            report['launch_preflight']=require_no_running_solidworks()
            checkpoint()
            with owned_solidworks(Path(request['sw_exe'])) as binding:
                from drawing_run import note_drawing_process
                note_drawing_process(current_lease())
                driver=TrialDriver(current_lease(),root,models,report)
                source=driver.open_document(assembly,readonly=True)
                config=str(source.ConfigurationManager.ActiveConfiguration.Name)
                model_kind=int(read_member(source,'GetType'))
                report['source_model_kind']='part' if model_kind==1 else 'assembly' if model_kind==2 else 'unsupported'
                for case in request['cases']:
                    tag=case['sheet']+'-1-'+str(case['denominator']);cell={'tag':tag,'status':'running'};report['cells'].append(cell);checkpoint()
                    task=trial_task(case,request['templates'][case['sheet']],config,request['bom_template'],model_kind=model_kind)
                    try:
                        cell['drawing']=driver.export_manufacturing({'status':'ready_for_native','tasks':[task]},{'documents':{'machine':{'path':str(assembly),'configuration':config}}},root/tag)
                        cell['status']='pass_pending_visual'
                        cell.update(acceptance_state='reviewing',delivery_accepted=False)
                    except (ValueError,RuntimeError) as error:
                        message=str(error);cell['error']=message
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
