"""Focused review regressions for PR23, fake operations only."""
import json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from run_recovery import RunLock,run_teardown_sequence,write_checkpoint,validate_checkpoint_chain,sha256_file,_pid_alive

class ReviewGuards(unittest.TestCase):
    def test_unprobeable_owner_is_not_dead(self):
        with patch('run_recovery.os.kill',side_effect=OSError('probe unavailable')):
            self.assertIsNone(_pid_alive(123))
        for pid in (None,-1,0,'123',True):self.assertIsNone(_pid_alive(pid))
    def test_unknown_owner_lock_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lock=root/'.part.lock';lock.mkdir()
            (lock/'owner.json').write_text(json.dumps({'pid':123,'heartbeat':time.time()-99999}))
            with patch('run_recovery._pid_alive',return_value=None):
                with self.assertRaisesRegex(RuntimeError,'unverified'):RunLock(root,'part',plan_id='p').acquire()
            self.assertTrue(lock.exists());self.assertEqual(list(root.glob('*.archived-*')),[])
    def steps(self,code=0,titles=()):
        return {'close_docs':lambda:[], 'enumerate_titles':lambda:list(titles),
                'exit_app':lambda:None,'release':lambda:{'ok':True},'poll_exit_code':lambda:code}
    def test_nonzero_and_pending_exit_never_green(self):
        for code in (139,3221225477,None,False):
            with self.subTest(code=code):
                r=run_teardown_sequence(self.steps(code));self.assertFalse(r['ok']);self.assertEqual(r['exit_code'],code)
        self.assertTrue(run_teardown_sequence(self.steps())['ok'])
    def test_nonempty_inventory_prevents_exit_call(self):
        steps=self.steps(titles=['foreign.SLDPRT']);called=[];steps['exit_app']=lambda:called.append('exit')
        r=run_teardown_sequence(steps);self.assertFalse(r['ok']);self.assertEqual(called,[])
    def test_failed_close_prevents_exit_call(self):
        steps=self.steps();called=[];steps['close_docs']=lambda:{'ok':False};steps['exit_app']=lambda:called.append('exit')
        self.assertFalse(run_teardown_sequence(steps)['ok']);self.assertEqual(called,[])
    def test_failed_release_report_not_green(self):
        steps=self.steps();steps['release']=lambda:{'ok':False,'failed':['model']}
        self.assertFalse(run_teardown_sequence(steps)['ok'])
    def test_checkpoint_external_product_never_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'output';base.mkdir();outside=root/'private';outside.write_bytes(b'fixture')
            for name in ('../private',str(outside),'C:\\private'):
                write_checkpoint(root/'checkpoints','S0',plan_id='p',code_sha256='c',products=[{'name':name,'sha256':sha256_file(outside)}])
                stage,_=validate_checkpoint_chain(root/'checkpoints',plan_id='p',code_sha256='c',base_dir=base)
                self.assertIsNone(stage)

if __name__=='__main__':unittest.main()
