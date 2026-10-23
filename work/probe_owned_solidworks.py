"""Windows ownership smoke check: spawn, verify empty process, exit; no CAD writes."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sw-exe', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    from sw_owned_launch import owned_solidworks
    from sw_session import run_on_task_sta
    def job():
        with owned_solidworks(args.sw_exe) as binding:
            pass
        return binding.evidence()
    try:
        result = run_on_task_sta(job,timeout=120,task_name='owned-session-no-cad-probe')
        report = {'status':'session_verified', 'cad_executed':False, 'session':result}
        rc = 0
    except Exception as exc:
        report = {'status':'failed', 'cad_executed':False, 'error':str(exc)}
        rc = 1
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
