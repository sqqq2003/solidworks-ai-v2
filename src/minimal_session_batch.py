"""Run each native teardown probe in a fresh Python process; no process kill."""
import json,subprocess,sys
from pathlib import Path


def run_batch(sw_exe,repeat,directory,*,timeout=330,popen=subprocess.Popen):
    if type(repeat) is not int or repeat<1:raise ValueError('positive native repetition count required')
    root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=False)
    results=[]
    for index in range(repeat):
        attempt=root/f'attempt-{index+1:03d}';attempt.mkdir()
        command=[sys.executable,'-X','utf8',str(Path(__file__).with_name('run_recovery.py')),
                 '--sw-exe',str(sw_exe),'--repeat','1']
        with (attempt/'stdout.json').open('w',encoding='utf-8') as out,(attempt/'stderr.log').open('w',encoding='utf-8') as err:
            process=popen(command,stdout=out,stderr=err,shell=False)
            try:code=process.wait(timeout=timeout);running=False
            except subprocess.TimeoutExpired:code=None;running=True
        row={'index':index+1,'worker_pid':process.pid,'returncode':code,'worker_may_be_running':running,
            'stdout':str(attempt/'stdout.json'),'stderr':str(attempt/'stderr.log'),'status':'failed'}
        if not running:
            try:
                report=json.loads((attempt/'stdout.json').read_text(encoding='utf-8-sig'))
                row['report']=report
                if type(code) is int and code==0 and report.get('status')=='teardown_clean':row['status']='reported_clean'
            except (ValueError,OSError):row['parse_error']='missing or invalid child report'
        results.append(row)
        if row['status']!='reported_clean':
            results.extend({'index':later+1,'status':'not_run','reason':'previous native lifetime requires review'} for later in range(index+1,repeat))
            break
    result={'status':'teardown_clean' if all(row['status']=='reported_clean' for row in results) else 'teardown_failed',
        'repetitions':results,'pending_windows_validation':True,'scope':'fresh CLI worker per owned native session'}
    (root/'batch.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
