"""Formula modeling: preview, materialize, inspect, map, review, apply, generate."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    preview=commands.add_parser('preview');preview.add_argument('rules',type=Path)
    for key in ('length','width','height'):preview.add_argument('--'+key,type=float,required=True)
    preview.add_argument('--inputs',type=Path);preview.add_argument('--out',type=Path,required=True)
    material=commands.add_parser('materialize');material.add_argument('preview',type=Path);material.add_argument('--out',type=Path,required=True)
    inspect=commands.add_parser('inspect');inspect.add_argument('source',type=Path);inspect.add_argument('--configuration',required=True)
    inspect.add_argument('--dimension',action='append',default=[])
    prepare=commands.add_parser('prepare');prepare.add_argument('preview',type=Path);prepare.add_argument('mappings',type=Path);prepare.add_argument('inspection',type=Path);prepare.add_argument('--out',type=Path,required=True)
    status=commands.add_parser('status');status.add_argument('workspace',type=Path)
    approve=commands.add_parser('approve');approve.add_argument('workspace',type=Path);approve.add_argument('--reviewer',required=True);approve.add_argument('--review-sha256',required=True)
    apply=commands.add_parser('apply');apply.add_argument('workspace',type=Path);apply.add_argument('--approval-sha256',required=True)
    generate=commands.add_parser('generate');generate.add_argument('preview',type=Path);generate.add_argument('--template',type=Path,required=True)
    generate.add_argument('--template-sha256',required=True);generate.add_argument('--reviewed-plan-sha256',required=True);generate.add_argument('--reviewer',required=True)
    for command in (inspect,apply,generate):
        command.add_argument('--sw-exe',type=Path,required=True);command.add_argument('--out',type=Path,required=True)
        command.add_argument('--request-key',required=True);command.add_argument('--state-db',type=Path)
        command.add_argument('--session-mode',choices=('auto','idle_existing','dedicated'),default='auto')
    args=parser.parse_args(argv)
    try:
        from project_delivery import read_json
        from drawing_review import atomic_json
        if args.command=='preview':
            from parametric_workspace import preview_parameters
            result=preview_parameters(args.length,args.width,args.height,spec_path=args.rules,
                input_values=read_json(args.inputs) if args.inputs else None)
            atomic_json(args.out,result,exclusive=True)
        elif args.command=='materialize':
            from parametric_functions.generate import materialize_part_plan
            result=materialize_part_plan(read_json(args.preview));atomic_json(args.out,result,exclusive=True)
        elif args.command=='inspect':
            from parametric_functions.api import inspect_native_part
            result=inspect_native_part(args.source,args.configuration,args.sw_exe,args.out,
                dimension_names=args.dimension,request_key=args.request_key,session_mode=args.session_mode,state_db=args.state_db)
        elif args.command=='prepare':
            from parametric_functions.workflow import prepare_edit_workspace
            inspection=read_json(args.inspection);inspection=inspection.get('inspection',inspection)
            result=prepare_edit_workspace(read_json(args.preview),read_json(args.mappings),inspection,args.out)
        elif args.command=='status':
            from parametric_functions.workflow import inspect_edit_workspace
            result=inspect_edit_workspace(args.workspace)
        elif args.command=='approve':
            from parametric_functions.workflow import approve_edit_workspace
            result=approve_edit_workspace(args.workspace,reviewer=args.reviewer,expected_review_sha256=args.review_sha256)
        elif args.command=='apply':
            from parametric_functions.api import execute_edit_workspace
            result=execute_edit_workspace(args.workspace,args.sw_exe,args.out,approval_sha256=args.approval_sha256,
                request_key=args.request_key,session_mode=args.session_mode,state_db=args.state_db)
        else:
            from parametric_functions.generate import generate_native_part
            result=generate_native_part(read_json(args.preview),args.sw_exe,args.template,args.out,
                reviewer=args.reviewer,reviewed_plan_sha256=args.reviewed_plan_sha256,
                expected_template_sha256=args.template_sha256,request_key=args.request_key,
                session_mode=args.session_mode,state_db=args.state_db)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if result.get('status') in {'failed','blocked','inspection_failed_no_writes','edit_preflight_failed_no_writes'} or result.get('phase')=='blocked':return 1
        return 3 if args.command in {'inspect','apply','generate','prepare','approve','status'} else 0
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,ArithmeticError) as error:
        print(json.dumps({'status':'failed','error':str(error),'manufacturing_approved':False},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
