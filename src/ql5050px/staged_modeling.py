"""Audited serial execution. Model success and cleanup success are independent."""
import hashlib,json,os,time
from pathlib import Path


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Journal:
    def __init__(self,path):self.path=Path(path)
    def record(self,phase,status,**evidence):
        row={'phase':phase,'status':status,'time':time.time(),**evidence}
        with self.path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())


def execute_part_job(plan,host,folder):
    """Host is already inside the proved STA. No unknown process shutdown."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    log=Journal(folder/'stages.jsonl')
    result={'modeling':'not_started','cleanup':'not_started','native_acceptance':'pending_windows_validation'}
    created=False
    try:
        host.preflight(plan,folder);log.record('preflight','ok')
        host.create();created=True;log.record('document','created')
        for feature in plan['features']:
            value=host.create_editable_feature(feature)
            host.rebuild();log.record('feature','rebuilt',id=feature['id'],source=feature.get('evidence'),native=value)
        host.verify_feature_tree([f['id'] for f in plan['features']]);log.record('readback','ok')
        output=folder/'part.SLDPRT';host.save(output)
        if not output.is_file() or not output.stat().st_size:raise RuntimeError('missing output after save')
        log.record('save','ok',sha256=hash_file(output),bytes=output.stat().st_size)
        host.close();created=False;log.record('close_before_reopen','ok')
        host.reopen(output);created=True;host.rebuild()
        result['readback']=host.verify_feature_tree([f['id'] for f in plan['features']])
        result.update(modeling='saved_reopened',output=str(output),sha256=hash_file(output))
        log.record('reopen','ok',readback=result['readback'])
    except Exception as exc:
        result.update(modeling='failed',error=type(exc).__name__+': '+str(exc));log.record('modeling','failed',error=result['error'])
    finally:
        try:
            if created:host.close()
            result['cleanup']='owned_document_closed';log.record('cleanup','document_closed')
        except Exception as exc:
            result.update(cleanup='failed',cleanup_error=str(exc));log.record('cleanup','failed',error=str(exc))
        # Persist before Python/COM process teardown; cannot certify its exit.
        result['process_exit']='pending_external_observation'
        (folder/'checkpoint.json').write_text(json.dumps(result,indent=2))
    return result


class MockHost:
    """Offline feature contract only, never writes a fake SLDPRT."""
    supported_feature_kinds={'sketch','extrude','cut','hole','fillet','chamfer','mirror','pattern','revolve','base_flange','sketched_bend','relief'}
    def inspect(self,plan):
        seen=set();rows=[]
        for f in plan['features']:
            if f['kind'] not in self.supported_feature_kinds:raise ValueError('unsupported mock feature')
            if not set(f.get('depends_on',[]))<=seen:raise ValueError('dependency order invalid')
            if not f.get('confirmed'):raise ValueError('unconfirmed feature')
            seen.add(f['id']);rows.append({'id':f['id'],'kind':f['kind'],'simulated':True})
        return {'features':rows,'status':'mock_only','cad_executed':False,'native_acceptance':'pending_windows_validation'}


def modeling_batch(request,output_dir=None):
    if output_dir is None:raise ValueError('batch requires isolated output_dir')
    root=Path(output_dir);resume=request.get('resume',False)
    root.mkdir(parents=True,exist_ok=resume)
    signature=hashlib.sha256(json.dumps(request.get('jobs',[]),sort_keys=True).encode()).hexdigest()
    spec=root/'request.sha256'
    if spec.exists() and spec.read_text()!=signature:raise ValueError('changed batch cannot resume')
    spec.write_text(signature)
    rows=[];ids=set()
    for job in request['jobs']:
        name=job['id']
        if not name.replace('-','').replace('_','').isalnum() or name in ids:raise ValueError('unique safe ids required')
        ids.add(name);path=root/(name+'.json')
        if path.exists() and resume:
            rows.append(json.loads(path.read_text()));continue
        try:result={'id':name,**MockHost().inspect(job['plan'])}
        except Exception as exc:result={'id':name,'status':'failed','error':str(exc)}
        with path.open('x') as stream:json.dump(result,stream,indent=2)
        rows.append(result)
    return {'results':rows,'status':'review_required','cad_executed':False,'plan':{},'native_acceptance':'pending_windows_validation'}
