"""Fresh-worker repeat contract; no native process created."""
import json,tempfile,unittest,subprocess
from pathlib import Path
from minimal_session_batch import run_batch

class BatchContracts(unittest.TestCase):
    def test_each_repetition_uses_single_run_worker(self):
        calls=[]
        def spawn(command,stdout,stderr,shell):
            calls.append(command);stdout.write(json.dumps({'status':'teardown_clean','repetitions':[{'exit_code':0}]}));stdout.flush()
            class Child:
                pid=45678
                def wait(self,timeout=None):return 0
            return Child()
        with tempfile.TemporaryDirectory() as tmp:
            result=run_batch('fake-SLDWORKS.exe',3,Path(tmp)/'batch',popen=spawn)
        self.assertEqual(len(calls),3);self.assertTrue(all(c[-1]=='1' for c in calls))
        self.assertEqual(result['status'],'teardown_clean')
    def test_failed_worker_stops_further_native_spawns(self):
        calls=[]
        def spawn(command,stdout,stderr,shell):
            calls.append(command)
            class Child:
                pid=45678
                def wait(self,timeout=None):return 139
            return Child()
        with tempfile.TemporaryDirectory() as tmp:result=run_batch('fake.exe',3,Path(tmp)/'batch',popen=spawn)
        self.assertEqual(len(calls),1);self.assertEqual([r['status'] for r in result['repetitions']],['failed','not_run','not_run'])

    def test_timeout_stops_without_killing_worker(self):
        killed=[]
        def spawn(command,stdout,stderr,shell):
            class Child:
                pid=45678
                def wait(self,timeout=None):raise subprocess.TimeoutExpired('fake',timeout)
                def kill(self):killed.append('kill')
                def terminate(self):killed.append('terminate')
            return Child()
        with tempfile.TemporaryDirectory() as tmp:result=run_batch('fake.exe',2,Path(tmp)/'batch',popen=spawn)
        self.assertTrue(result['repetitions'][0]['worker_may_be_running']);self.assertEqual(killed,[])
        self.assertEqual(result['repetitions'][1]['status'],'not_run')

if __name__=='__main__':unittest.main()
