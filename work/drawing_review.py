"""Inspect evidence or record a named human visual decision; never starts CAD."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('inspect');a.add_argument('evidence',type=Path)
    a=sub.add_parser('batch');a.add_argument('directory',type=Path)
    a=sub.add_parser('export');a.add_argument('directory',type=Path);a.add_argument('--out',type=Path,required=True);a.add_argument('--revision',required=True)
    a=sub.add_parser('review');a.add_argument('evidence',type=Path)
    a.add_argument('--reviewer',required=True);a.add_argument('--evidence-sha256',required=True)
    a.add_argument('--decision',choices=('accepted','rejected'),required=True)
    a.add_argument('--checklist',type=Path,required=True);a.add_argument('--notes',default='')
    args=p.parse_args(argv)
    try:
        from drawing_review import inspect_drawing,inspect_drawing_batch,review_drawing
        if args.command=='inspect':result=inspect_drawing(args.evidence)
        elif args.command=='batch':result=inspect_drawing_batch(args.directory)
        elif args.command=='export':
            from drawing_review import export_visual_review
            result=export_visual_review(args.directory,args.out,source_revision=args.revision)
        else:
            from project_delivery import read_json
            result=review_drawing(args.evidence,reviewer=args.reviewer,expected_sha256=args.evidence_sha256,
                decision=args.decision,checklist=read_json(args.checklist),notes=args.notes)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 0 if result.get('delivery_accepted') else 1 if result.get('state') in {'failed','rejected'} else 3
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as error:
        print(json.dumps({'state':'reviewing','error':str(error),'delivery_accepted':False},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
