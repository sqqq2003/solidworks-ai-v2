"""Serial native worker supervision: never kills CAD or treats crash as success."""
import json,subprocess,sys,hashlib,time,threading
from pathlib import Path


def supervise(jobs,root,*,resume=False,timeout=900):
    root=Path(root);root.mkdir(parents=True,exist_ok=resume)
    signature=hashlib.sha256(json.dumps(jobs,sort_keys=True,allow_nan=False).encode()).hexdigest()
    spec=root/'batch.sha256'
    if spec.exists() and spec.read_text()!=signature:raise ValueError('resume input changed')
    spec.write_text(signature)
    results=[];ids=set()
    for job in jobs:
        name=job['id']
        if not name.replace('_','').replace('-','').isalnum() or name in ids:raise ValueError('safe unique job ids required')
        ids.add(name)
    for job in jobs:
        folder=root/job['id'];folder.mkdir(exist_ok=True)
        attempts=sorted(folder.glob('attempt-*'))
        if attempts:
            latest=attempts[-1]/'supervisor.json'
            if not latest.exists():raise RuntimeError('incomplete worker attempt; inspect PID/logs before retry')
            old=json.loads(latest.read_text())
            if old.get('worker_may_be_running'):raise RuntimeError('unresolved worker blocks further native work')
            if old.get('status')=='completed':results.append(old);continue
        attempt=folder/f'attempt-{len(attempts)+1:06d}';attempt.mkdir()
        request=attempt/'request.json';request.write_text(json.dumps(job))
        output=attempt/'model'
        command=[sys.executable,'-X','utf8','-m','ql5050px.modeling_worker',str(request),str(output)]
        with (attempt/'stdout.log').open('x') as out,(attempt/'stderr.log').open('x') as err:
            process=subprocess.Popen(command,stdout=out,stderr=err,shell=False)
            (attempt/'worker.json').write_text(json.dumps({'pid':process.pid,'command':command,'started':time.time()}))
            try:code=process.wait(timeout=timeout);running=False
            except subprocess.TimeoutExpired:
                code=None;running=True
                threading.Thread(target=process.wait,daemon=True).start()
        checkpoint=output/'checkpoint.json';model=json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        row={'id':job['id'],'returncode':code,'worker_pid':process.pid,'worker_may_be_running':running,
             'modeling':model.get('modeling','unknown'),'cleanup':model.get('cleanup','unknown'),
             'status':'completed' if code==0 and model.get('modeling')=='saved_reopened' and model.get('cleanup')=='owned_document_closed' else 'needs_review',
             'native_acceptance':'pending_windows_validation','attempt':str(attempt)}
        (attempt/'supervisor.json').write_text(json.dumps(row,indent=2));results.append(row)
        if running:break # never overlap an uncertain native writer
    return {'results':results,'status':'review_required','native_acceptance':'pending_windows_validation'}
