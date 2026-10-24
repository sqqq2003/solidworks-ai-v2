"""Generate the single planning/OEM/test package; this does not run tests."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ql5050px.machine_package import write_machine_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--revision',help='explicit source revision when checkout metadata is absent')
    args = parser.parse_args()
    revision = args.revision or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    request = json.loads(args.config.read_text(encoding='utf-8-sig'))
    receipt = write_machine_package(request,args.out,source_revision=revision)
    print(json.dumps({k:v for k,v in receipt.items() if k!='plan'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
