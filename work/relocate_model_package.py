"""Relocate only hash-verified test-package references on the target PC."""
import argparse,hashlib,json,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]


def relocate(package,executable,*,session_factory=None):
    from app_logging import get_journal
    journal=get_journal()
    journal.record('reference_relocation_started',package=str(package),sw_exe=str(executable))
    from sw_session import run_on_task_sta
    from sw_owned_launch import owned_solidworks
    from src.ql5050px.drawing_trial import require_no_running_solidworks
    package=Path(package).resolve();manifest=json.loads((package/'portable-models.json').read_text(encoding='utf-8'))
    files={}
    for row in manifest['files']:
        path=(package/row['path']).resolve()
        if not path.is_relative_to(package) or not path.is_file():raise ValueError('invalid package file')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('model baseline changed; use a fresh extraction: '+row['path'])
        files[Path(row['path']).as_posix()]=path
    dependencies=[]
    for row in manifest['dependencies']:
        owner=Path(row['owner']).as_posix();target=Path(row['target']).as_posix()
        if owner not in files or target not in files:raise ValueError('dependency owner or target missing from verified manifest')
        dependencies.append(dict(row,owner=owner,target=target))
    report={'status':'running','changes':[],'production_approved':False}
    def save():
        (package/'relocation-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def job():
        if session_factory is None:require_no_running_solidworks()
        factory=session_factory or owned_solidworks
        with factory(Path(executable)) as binding:
            app=binding.app
            for row in dependencies:
                owner=files[row['owner']];target=files[row['target']]
                ok=bool(app.ReplaceReferencedDocument(str(owner),row['old_path'],str(target)))
                report['changes'].append({'owner':row['owner'],'target':row['target'],'success':ok});save()
                journal.record('reference_updated',owner=row['owner'],target=row['target'],success=ok)
                if not ok:raise RuntimeError('reference update rejected; retain diagnostics')
            for owner in files.values():
                values=list(app.GetDocumentDependencies2(str(owner),False,False,False) or [])
                for dep in values[1::2]:
                    path=Path(dep)
                    if path.is_file() and not path.resolve().is_relative_to(package):raise RuntimeError('resolved external dependency remains')
            report['status']='references_relocated_remaining_four_types_unavailable'
        report['session']=binding.evidence()
    try:run_on_task_sta(job,timeout=600,task_name='relocate-verified-test-package')
    except Exception as error:
        journal.exception('reference_relocation_failed',error)
        report.update(status='failed',error=str(error),traceback=traceback.format_exc())
    journal.record('reference_relocation_finished',status=report['status'],updated=len(report['changes']))
    save();return report


if __name__=='__main__':
    from app_logging import bootstrap
    bootstrap(ROOT,'reference-relocation')
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True);parser.add_argument('--sw-exe',required=True);args=parser.parse_args()
    result=relocate(args.package,args.sw_exe);print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(1 if result['status']=='failed' else 0)
