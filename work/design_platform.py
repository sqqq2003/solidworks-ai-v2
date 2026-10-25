"""Unified offline design platform: plan/package, bindings, history, knowledge, UI."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    delivery=sub.add_parser('package');delivery.add_argument('request',type=Path);delivery.add_argument('--out',type=Path,required=True)
    natural=sub.add_parser('instruction');natural.add_argument('text')
    binding=sub.add_parser('approve-binding');binding.add_argument('report',type=Path);binding.add_argument('approval',type=Path);binding.add_argument('--out',type=Path,required=True)
    snapshot=sub.add_parser('snapshot');snapshot.add_argument('specification',type=Path);snapshot.add_argument('--store',type=Path,required=True)
    restore=sub.add_parser('restore');restore.add_argument('revision');restore.add_argument('--store',type=Path,required=True);restore.add_argument('--out',type=Path,required=True)
    history=sub.add_parser('history');history.add_argument('--store',type=Path,required=True)
    case=sub.add_parser('add-case');case.add_argument('case',type=Path);case.add_argument('--database',type=Path,required=True);case.add_argument('--evidence-root',type=Path)
    search=sub.add_parser('search-cases');search.add_argument('query');search.add_argument('--context',type=Path,required=True);search.add_argument('--database',type=Path,required=True)
    sub.add_parser('gui');args=p.parse_args()
    def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
    try:
        if args.action=='package':
            from design_platform.workflow import build_delivery
            result=build_delivery(read(args.request),args.out)
        elif args.action=='instruction':
            from design_platform.assistant import parse_request
            result=parse_request(args.text)
        elif args.action=='approve-binding':
            from design_platform.mapping import approve_binding
            result=approve_binding(read(args.report),read(args.approval))
            with args.out.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        elif args.action=='snapshot':
            from design_platform.projects import commit_revision
            spec=read(args.specification);result=commit_revision(args.store,spec['files'],spec['metadata'],parent=spec.get('parent'))
        elif args.action=='restore':
            from design_platform.projects import restore_revision
            result=restore_revision(args.store,args.revision,args.out)
        elif args.action=='history':
            from design_platform.projects import history
            result={'status':'history_read','revisions':history(args.store)}
        elif args.action=='add-case':
            from design_platform.knowledge import add_case
            result=add_case(args.database,read(args.case),evidence_root=args.evidence_root)
        elif args.action=='search-cases':
            from design_platform.knowledge import search_cases
            result={'status':'review_required','cases':search_cases(args.database,args.query,read(args.context))}
        else:
            from design_platform.desktop import main as gui
            gui();return 0
        print(json.dumps(result,ensure_ascii=False,indent=2));return 1 if result.get('status')=='failed' else 3 if result.get('status') in {'pending_mapping','review_required'} else 0
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
