"""python -m ql5050px {parameters,assembly,sheet,bom} INPUT.json [--output PATH]."""
import argparse
import json
from pathlib import Path
from .parameters import build_plan
from .assembly import inspect_assembly
from .sheet_metal import unfold_strip, export_blank_dxf
from .drawing_bom import build_bom, export_bom_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module",choices=["parameters","assembly","sheet","bom"])
    parser.add_argument("input",type=Path)
    parser.add_argument("--output",type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if args.module == "parameters":
        result = build_plan(**payload)
    elif args.module == "assembly":
        result = inspect_assembly(**payload)
    elif args.module == "sheet":
        result = unfold_strip(**payload)
        if args.output:
            export_blank_dxf(result,args.output)
    else:
        result = build_bom(payload["components"])
        if args.output:
            export_bom_csv(result,args.output)
    if args.output and args.module in {"parameters","assembly"}:
        with args.output.open("x",encoding="utf-8") as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__ == "__main__":
    main()
