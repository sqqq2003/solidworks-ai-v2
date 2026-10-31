"""Read-only audit of the JSON emitted by work/run_sheet_metal.py."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sheet_metal_acceptance import audit_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    args=parser.parse_args()
    try:
        result=audit_report(json.loads(args.report.read_text(encoding='utf-8-sig')))
    except (OSError,ValueError,TypeError) as error:
        result=dict(status='review_required',issues=[str(error)],cad_executed=False)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='evidence_consistent' else 3

if __name__=='__main__':
    raise SystemExit(main())
