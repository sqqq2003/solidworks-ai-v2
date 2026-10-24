"""Owned-session math-only retest; never starts p248 or saves a document."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sw-exe',type=Path,required=True);a=p.parse_args()
    from sw_session import run_on_task_sta,current_lease
    from sw_owned_launch import owned_solidworks
    from sw_math_arrays import oracle
    def job():
        import pythoncom,win32com.client,solidworks_generator as sw
        with owned_solidworks(a.sw_exe):
            app,_=sw._connect_task_solidworks(current_lease(),win32com,pythoncom)
            return oracle(app,[{'transform':[0,1,0,-1,0,0,0,0,1,.01,.02,0,1,0,0,0],'point':[.03,.04,0]},
                {'transform':[1,0,0,0,1,0,0,0,1,10,20,30,2,0,0,0],'point':[1,2,3]}])
    result=run_on_task_sta(job,timeout=120,task_name='math-oracle')
    print(json.dumps(result,indent=2));return 0 if result['oracle_ok'] else 1
if __name__=='__main__':raise SystemExit(main())
