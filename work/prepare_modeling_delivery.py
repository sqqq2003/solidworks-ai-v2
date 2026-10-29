"""Generate one auditable recipe/Windows matrix package without running SW."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from ql5050px.modeling_delivery import export_delivery

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();result=export_delivery(json.loads(a.manifest.read_text(encoding='utf-8-sig')),a.out)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
