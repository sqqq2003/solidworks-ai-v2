"""Serial native worker supervision: never kills CAD or treats crash as success."""
import json,subprocess,sys,hashlib,time,threading,os
from pathlib import Path


def _supervise_locked(jobs,root,*,resume=False,timeout=900,stop_requested=lambda:False):
    root=Path(root).resolve()
    source=Path(__file__).resolve().parent
    engine=source.parent
    version_files=list(source.glob('*.py'))
    version_files += [engine/name for name in ('solidworks_generator.py','sheet_metal_pipeline.py','sheet_metal_windows.py','turned_part.py','turned_generate.py','cad_analyzer.py','profile_sanitize.py','profile_selection.py','bend_allowance.py','part_verification.py','sw_session.py','sw_owned_launch.py','owned_document_lifetime.py')]
    code={str(p.relative_to(engine)):hashlib.sha256(p.read_bytes()).hexdigest() for p in version_files if p.is_file()}
    signature=hashlib.sha256(json.dumps({'jobs':jobs,'code':code},sort_keys=True,allow_nan=False).encode()).hexdigest()
    spec=root/'batch.sha256'
    if spec.exists() and spec.read_text()!=signature:raise ValueError('resume input changed')
    spec.write_text(signature)
    (root/'source-manifest.json').write_text(json.dumps({'code_sha256':code,'request_and_code_signature':signature,'native_acceptance':'pending_windows_validation'},indent=2))
    results=[];ids=set()
    for job in jobs:
        name=job['id']
        if not name.replace('_','').replace('-','').isalnum() or name in ids:raise ValueError('safe unique job ids required')
        ids.add(name)
    for index,job in enumerate(jobs):
        if stop_requested():
            results.append({'id':job['id'],'status':'not_run','reason':'stopped after previous worker'});continue
        folder=root/job['id'];folder.mkdir(exist_ok=True)
        attempts=sorted(folder.glob('attempt-*'))
        if attempts:
            latest=attempts[-1]/'supervisor.json'
            if not latest.exists():raise RuntimeError('incomplete worker attempt; inspect PID/logs before retry')
            old=json.loads(latest.read_text())
            if old.get('worker_may_be_running'):raise RuntimeError('unresolved worker blocks further native work')
            if (old.get('exit_class')=='native_access_violation' or old.get('cleanup') in {'failed','needs_review','unknown',None}) and not old.get('recovery_approved'):
                raise RuntimeError('crashed worker requires explicit recover-parts review before retry')
            if old.get('status')=='completed':
                artifact=old.get('artifact',{})
                path=Path(artifact.get('path',''))
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=artifact.get('sha256'):
                    raise ValueError('completed artifact missing/changed; use new batch directory')
                for relative,checksum in old.get('artifacts',{}).items():
                    item=(root/relative).resolve()
                    if not item.is_relative_to(root) or not item.is_file() or hashlib.sha256(item.read_bytes()).hexdigest()!=checksum:
                        raise ValueError('completed native artifacts changed; use a new output directory')
                results.append(old);continue
        attempt=folder/f'attempt-{len(attempts)+1:06d}';attempt.mkdir()
        request=attempt/'request.json';request.write_text(json.dumps(job),encoding='utf-8')
        output=attempt/'model'
        command=[sys.executable,'-X','utf8','-m','ql5050px.modeling_worker',str(request),str(output)]
        with (attempt/'stdout.log').open('x') as out,(attempt/'stderr.log').open('x') as err:
            env=dict(os.environ)
            source=str(Path(__file__).resolve().parents[1])
            env['PYTHONPATH']=source+os.pathsep+env.get('PYTHONPATH','')
            process=subprocess.Popen(command,stdout=out,stderr=err,shell=False,env=env)
            (attempt/'worker.json').write_text(json.dumps({'pid':process.pid,'command':command,'started':time.time()}))
            try:code=process.wait(timeout=timeout);running=False
            except subprocess.TimeoutExpired:
                code=None;running=True
                threading.Thread(target=process.wait,daemon=True).start()
        checkpoint=output/'checkpoint.json'
        try:model=json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        except (OSError,ValueError):model={'modeling':'unknown','cleanup':'unknown','checkpoint_error':'unreadable; inspect stage log'}
        crash = code in (139,-11,-1073741819,3221225477)
        row={'id':job['id'],'returncode':code,'exit_class':'native_access_violation' if crash else ('timeout' if running else ('normal' if code==0 else 'worker_error')),'worker_pid':process.pid,'worker_may_be_running':running,
             'modeling':model.get('modeling','unknown'),'cleanup':model.get('cleanup','unknown'),
             'status':'completed' if code==0 and model.get('modeling')=='saved_reopened' and model.get('cleanup')=='owned_document_closed' else 'needs_review',
             'native_acceptance':'pending_windows_validation','attempt':str(attempt)}
        if model.get('flat_export',{}).get('path'):
            row['flat_export']=model['flat_export']
        if model.get('output') and Path(model['output']).resolve().is_relative_to(root) and Path(model['output']).is_file():
            row['artifact']={'path':model['output'],'sha256':hashlib.sha256(Path(model['output']).read_bytes()).hexdigest()}
        row['artifacts']={}
        if output.is_dir():
            for artifact in output.rglob('*'):
                if artifact.is_file() and artifact.suffix.lower() in {'.sldprt','.dxf'}:
                    if artifact.is_symlink() or not artifact.resolve().is_relative_to(root):raise ValueError('external artifact link refused')
                    row['artifacts'][str(artifact.relative_to(root))]=hashlib.sha256(artifact.read_bytes()).hexdigest()
        (attempt/'supervisor.json').write_text(json.dumps(row,indent=2));results.append(row)
        if crash:
            (attempt/'CRASH_REVIEW.json').write_text(json.dumps({'pid':process.pid,'checkpoint':str(checkpoint),'native_exit':code,'instruction':'Preserve checkpoint/logs. Inspect SW session; do not infer success or kill unknown processes.'},indent=2))
        if running or crash or model.get('cleanup') in {'failed','needs_review','unknown',None}:
            results.extend({'id':later['id'],'status':'not_run','reason':'previous worker lifetime requires review'} for later in jobs[index+1:])
            break
    summary={'results':results,'status':'review_required','native_acceptance':'pending_windows_validation',
        'counts':{s:sum(r['status']==s for r in results) for s in sorted({r['status'] for r in results})}}
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    return summary


def supervise(jobs,root,*,resume=False,timeout=900,stop_requested=lambda:False):
    if not isinstance(jobs,list) or not jobs:raise ValueError('nonempty native jobs list required')
    if type(timeout) not in (int,float) or not __import__('math').isfinite(timeout) or timeout<=0:
        raise ValueError('finite positive timeout required')
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=resume)
    lock=root/'.supervisor.lock'
    descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        os.write(descriptor,json.dumps({'supervisor_pid':os.getpid(),'started':time.time()}).encode())
        return _supervise_locked(jobs,root,resume=resume,timeout=timeout,stop_requested=stop_requested)
    finally:
        os.close(descriptor);lock.unlink()


