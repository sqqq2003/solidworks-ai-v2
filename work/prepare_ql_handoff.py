"""Build one source-only QL handoff bundle with actual checkout revision."""
import argparse
import json
from pathlib import Path
import subprocess
from prepare_test_handoff import build_package

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    print(json.dumps(build_package(ROOT,args.out,revision),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
