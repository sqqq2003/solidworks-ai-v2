"""Run/resume a declared manufacturing pipeline; native jobs remain disabled.

All numbers in the bundled example pipeline are simulation fixture inputs.
This development batch does not execute the example or count it as a test.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from ql5050px.manufacturing import offline_runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pipeline",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--resume",action="store_true")
    args = parser.parse_args()
    jobs = json.loads(args.pipeline.read_text(encoding="utf-8"))
    result = offline_runner().run(jobs,args.output,resume=args.resume)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 1 if result["counts"]["failed"] or result["counts"]["blocked"] else 0


if __name__=="__main__":
    raise SystemExit(main())
