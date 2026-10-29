"""One worker lifetime per native part. External parent observes final exit."""
import json,sys,faulthandler,os
from pathlib import Path
from .native_part_host import run_native_part

def main():
    faulthandler.enable(all_threads=True)
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    root=Path(sys.argv[2]);root_existed=root.exists()
    try:
        if 'recipe' in request:
            from .recipe_worker import run_recipe_job
            result=run_recipe_job(request,sys.argv[2])
        else:
            result=run_native_part(request['sw_exe'],request['template'],request['plan'],sys.argv[2])
    except Exception as exc:
        from .staged_modeling import atomic_checkpoint
        root=Path(sys.argv[2]);checkpoint=root/'checkpoint.json'
        if not root_existed and root.is_dir() and checkpoint.is_file():
            try:result=json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.is_file() else {'modeling':'unknown'}
            except (OSError,ValueError):result={'modeling':'unknown'}
            if result.get('worker_pid')!=os.getpid():raise
            result.update(cleanup='needs_review',session_error=type(exc).__name__+': '+str(exc),native_acceptance='pending_windows_validation')
            result['native_session_evidence']=getattr(exc,'native_session_evidence',None)
            atomic_checkpoint(checkpoint,result)
        raise
    print(json.dumps(result))
    return 0 if result['modeling']=='saved_reopened' and result['cleanup']=='owned_document_closed' else 1
if __name__=='__main__':raise SystemExit(main())

