"""Prepare one-dimension rehearsal or audit Gork evidence; never starts CAD."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ql5050px.variant_acceptance import prepare_case,evidence_template,audit_case


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare')
    prepare.add_argument('--request',type=Path,required=True)
    prepare.add_argument('--out',type=Path,required=True)
    audit=commands.add_parser('audit')
    audit.add_argument('--case',type=Path,required=True)
    audit.add_argument('--evidence',type=Path,required=True)
    audit.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='prepare':
            result=prepare_case(read(args.request))
            args.out.mkdir(parents=True,exist_ok=False)
            documents={'case.json':result,'evidence-template.json':evidence_template(result)}
            for name,data in documents.items():
                (args.out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            print(json.dumps({'status':result['status'],'case_id':result['case_id'],'blockers':result['blockers']},ensure_ascii=False))
            return 3 if result['blockers'] else 0
        result=audit_case(read(args.case),read(args.evidence),args.evidence.parent)
        # Never overwrite collected evidence or an earlier report.
        with args.out.open('x',encoding='utf-8') as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status']=='evidence_consistent' else 3
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
        print(json.dumps({'status':'failed','error':str(error),'production_release':False},ensure_ascii=False))
        return 1


if __name__=='__main__': raise SystemExit(main())
