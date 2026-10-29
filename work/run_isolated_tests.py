"""Offline regression with one subprocess per test module to isolate global mocks."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
CHILD="""import json,os,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'src')]
import sw_session
# Like run_cloud_tests.py, these jobs use fake COM only. Their ownership
# probes must not contend with a live native acceptance writer.
sw_session._WRITER_MUTEX_NAME = 'Local\\\\A01IsolatedTests-' + str(os.getpid())
sw_session._WRITER_LOCK_FILE = Path(tempfile.gettempdir()) / ('a01-isolated-tests-' + str(os.getpid()) + '.lock')
suite=unittest.TestLoader().discover(sys.argv[1],pattern=sys.argv[2])
result=unittest.TextTestRunner(verbosity=1).run(suite)
print(json.dumps(dict(run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped))))
"""

def main():
    out=ROOT/'results/cloud/isolated'
    out.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'PYTHONUTF8':'1'}
    rows=[]
    files=[('tests',p.name) for p in sorted((ROOT/'tests').glob('test_*.py'))]
    files += [('work','test_review_session_boundaries.py')]
    if len(sys.argv)>1:
        files=[row for row in files if row[1]==sys.argv[1]]
        if not files:
            raise ValueError('test module not found')
    for folder,name in files:
        try:
            result=subprocess.run([sys.executable,'-X','utf8','-c',CHILD,folder,name],cwd=ROOT,
                env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
            (out/(name+'.log')).write_text(result.stderr+'\n'+result.stdout,encoding='utf-8')
            row=json.loads(result.stdout.strip().splitlines()[-1])
            row.update(module=name,process_exit=result.returncode)
        except (OSError,ValueError,IndexError,subprocess.TimeoutExpired) as error:
            row=dict(module=name,run=0,failures=0,errors=1,skipped=0,process_error=type(error).__name__)
        rows.append(row)
        print(json.dumps(row),flush=True)
    total={key:sum(r[key] for r in rows) for key in ('run','failures','errors','skipped')}
    total.update(scope='isolated_offline_tests_only',cad_executed=False,modules=rows)
    total['passed']=total['run']-total['failures']-total['errors']-total['skipped']
    (out/('summary-'+sys.argv[1]+'.json' if len(sys.argv)>1 else 'summary.json')).write_text(json.dumps(total,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in total.items() if k!='modules'}))
    return int(bool(total['failures'] or total['errors'] or any(r.get('process_exit',0) for r in rows)))

if __name__=='__main__':
    raise SystemExit(main())
