"""One CLI for candidate packaging, persistent design workflow and evidence inbox."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from project_delivery import read_json,write_new


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('candidate');p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--out',type=Path,required=True);p.add_argument('--revision');p.add_argument('--source-index',type=Path)
    p=sub.add_parser('verify-candidate');p.add_argument('directory',type=Path)
    p=sub.add_parser('prepare');p.add_argument('request',type=Path);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('status');p.add_argument('workspace',type=Path)
    p=sub.add_parser('approve');p.add_argument('workspace',type=Path);p.add_argument('--reviewer',required=True);p.add_argument('--review-sha256',required=True)
    p=sub.add_parser('execute');p.add_argument('workspace',type=Path);p.add_argument('--sw-exe',type=Path,required=True);p.add_argument('--approval-sha256',required=True)
    p=sub.add_parser('diagnose');p.add_argument('archive',type=Path);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('audit');p.add_argument('matrix',type=Path);p.add_argument('submission',type=Path);p.add_argument('--evidence-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='candidate':
            from release_candidate import build_candidate
            result=build_candidate(args.root,args.out,expected_revision=args.revision,source_index=read_json(args.source_index) if args.source_index else None)
        elif args.command=='verify-candidate':
            from release_candidate import verify_candidate
            result=verify_candidate(args.directory)
        elif args.command=='prepare':
            from project_delivery import prepare_workflow
            result=prepare_workflow(read_json(args.request),args.out)
        elif args.command=='status':
            from project_delivery import workflow_status
            result=workflow_status(args.workspace)
        elif args.command=='approve':
            from project_delivery import approve_workflow
            result=approve_workflow(args.workspace,reviewer=args.reviewer,review_sha256=args.review_sha256)
        elif args.command=='execute':
            from project_delivery import execute_workflow
            result=execute_workflow(args.workspace,sw_exe=args.sw_exe,approval_sha256=args.approval_sha256)
        elif args.command=='diagnose':
            from release_evidence import inspect_diagnostics
            result=inspect_diagnostics(args.archive);write_new(args.out,result)
        else:
            from release_evidence import audit_submission
            result=audit_submission(read_json(args.matrix),read_json(args.submission),args.evidence_root)
            args.out.mkdir(parents=True,exist_ok=False)
            write_new(args.out/'audit.json',result)
            write_new(args.out/'repair-tasks.json',{'schema_version':1,'tasks':result['repair_tasks']})
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 1 if result.get('status')=='failed' else 3 if result.get('status') in {'review_required','degraded'} or result.get('native_acceptance')=='not_run' else 0
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
        print(json.dumps({'status':'failed','error':str(exc),'manufacturing_approved':False},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
