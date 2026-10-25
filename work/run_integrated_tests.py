"""Run repository regression and independent offline contracts, with one receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    root=args.out.resolve();root.mkdir(parents=True,exist_ok=False)
    commands=[('repository',[sys.executable,'work/run_cloud_tests.py']),
              ('original-feature-contracts',[sys.executable,'-m','unittest','discover','-s','tests/pending_features','-v']),
              ('feature-tree',[sys.executable,'-m','unittest','discover','-s','feature_tree/tests','-v']),
              ('geometry-ir',[sys.executable,'-m','unittest','discover','-s','geometry_ir/tests','-v'])]
    suites=[]
    for name,command in commands:
        process=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        stdout=root/(name+'.stdout.log');stderr=root/(name+'.stderr.log')
        stdout.write_text(process.stdout,encoding='utf-8');stderr.write_text(process.stderr,encoding='utf-8')
        record={'id':name,'command':command,'returncode':process.returncode,'status':'passed' if process.returncode==0 else 'failed'}
        if name=='repository':
            report=json.loads((ROOT/'results/cloud/latest.json').read_text(encoding='utf-8'))
            record.update(run=report['tests_run'],passed=report['passed'],skipped=len(report['skipped']),
                skip_reasons=report['skipped'],failures=report['failures'],errors=report['errors'],cross_process_lock_passed=report['cross_process_lock_passed'])
            if report['failures'] or report['errors'] or not report['cross_process_lock_passed']:record['status']='failed'
        else:
            count=re.search(r'Ran (\d+) tests?',process.stderr)
            if not count:record['status']='failed';record['error']='missing unittest summary'
            record.update(run=int(count[1]) if count else 0,skipped=0,passed=int(count[1]) if count and process.returncode==0 else 0)
        record['logs_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (stdout,stderr)}
        suites.append(record)
    report={'scope':'integrated_offline_only','status':'passed' if all(r['status']=='passed' for r in suites) else 'failed',
            'run':sum(r['run'] for r in suites),'passed':sum(r['passed'] for r in suites),'skipped':sum(r['skipped'] for r in suites),
            'suites':suites,'solidworks_live_verified':False,'native_acceptance':'pending_windows_validation'}
    (root/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
