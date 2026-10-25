"""Reproduce last-document auto-exit using fake COM and the real STA/write gate."""
from pathlib import Path
import subprocess,tempfile,unittest
from unittest.mock import MagicMock,patch
from types import SimpleNamespace
import sw_session as session
from sw_owned_launch import bind_spawned
from owned_document_lifetime import finish_owned_session,release_closed_session_references

class Lifetime:
    pid=43810
    executable=r'C:\Program Files\SOLIDWORKS\SLDWORKS.exe'
    def __init__(self):
        self.alive=True;self.code=None
        self.process=SimpleNamespace(poll=lambda:self.code,wait=self.wait)
    def wait(self,timeout=None):
        if self.code is None:raise subprocess.TimeoutExpired('fakeSW',timeout)
        return self.code
    def probe(self,pid):
        return session.ProcessProbeInfo(self.pid,True,self.executable) if self.alive and pid==self.pid else None

class FakeApp:
    def __init__(self,lifetime,template,exit_code=0,disconnect_after_close=False):
        self.life=lifetime;self.template=template;self.docs=[];self.created=0;self.closed=[];self.exit_calls=0
        self.exit_code=exit_code;self.disconnect_after_close=disconnect_after_close;self.UserControl=False
    def GetProcessID(self):
        if not self.life.alive:raise RuntimeError(-2147220995,'CO_E_OBJNOTCONNECTED')
        return self.life.pid
    def GetUserPreferenceStringValue(self,kind):return self.template
    def NewDocument(self,*args):
        self.created+=1;title='keepalive-'+str(self.created);self.docs.append(title)
        return SimpleNamespace(GetTitle=lambda:title,GetType=lambda:1)
    def CloseDoc(self,title):
        self.closed.append(title);self.docs.remove(title)
        if not self.docs:
            self.life.alive=False;self.life.code=self.exit_code
            if self.disconnect_after_close:raise RuntimeError(-2147220995,'CO_E_OBJNOTCONNECTED')
    def ExitApp(self):
        self.exit_calls+=1;self.life.alive=False;self.life.code=self.exit_code

class AnchorContracts(unittest.TestCase):
    def setUp(self):
        session.reset_for_tests();self.addCleanup(session.reset_for_tests)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.template=Path(self.tmp.name)/'blank.prtdot';self.template.touch()
    def run_owned(self,call,**options):
        life=Lifetime();app=FakeApp(life,str(self.template),**options)
        def job():
            binding=bind_spawned(life,lambda pid:app,lambda a:a.GetProcessID(),lambda a:list(a.docs),timeout=1)
            lease=session.current_lease();app.docs.append('part.SLDPRT');lease.note_owned_document('part.SLDPRT')
            return call(lease,binding,app,life)
        return session.run_on_task_sta(job,timeout=5,task_name='fake-anchor-contract')
    def test_original_last_close_auto_exits_despite_usercontrol(self):
        life=Lifetime();app=FakeApp(life,str(self.template));app.UserControl=True;app.docs=['part.SLDPRT']
        app.CloseDoc('part.SLDPRT');self.assertFalse(life.alive)
    def test_anchor_keeps_same_process_alive_across_close_and_reopen(self):
        def exercise(lease,binding,app,life):
            session.close_owned_document(lease,app,'part.SLDPRT')
            self.assertTrue(life.alive);self.assertEqual(app.created,1)
            self.assertEqual(app.docs,[lease.keepalive_document_title])
            session.require_model_write(lease)
            app.docs.append('part.SLDPRT');lease.note_owned_document('part.SLDPRT')
            session.close_owned_document(lease,app,'part.SLDPRT')
            self.assertTrue(life.alive);self.assertEqual(app.created,1)
            lease.keep_application_open=False;finish_owned_session(lease,binding)
            self.assertEqual(binding.cleanup_status,'process_exited_cleanly');self.assertIsNone(binding.cleanup_error)
            self.assertEqual(life.code,0);self.assertEqual(app.exit_calls,0)
            release_closed_session_references(lease,binding)
            self.assertIsNone(binding.app);self.assertIsNone(lease.app_for_recycle)
        self.run_owned(exercise)
    def test_anchor_is_not_closed_by_intermediate_request(self):
        def exercise(lease,binding,app,life):
            session.close_owned_document(lease,app,'part.SLDPRT')
            with self.assertRaisesRegex(session.SessionOwnershipError,'anchor refused'):
                session.close_owned_document(lease,app,lease.keepalive_document_title)
            self.assertTrue(life.alive)
        self.run_owned(exercise)
    def test_missing_template_refuses_close_without_touching_original(self):
        def exercise(lease,binding,app,life):
            app.template=str(Path(self.tmp.name)/'missing.prtdot')
            with self.assertRaisesRegex(session.SessionOwnershipError,'template required'):session.close_owned_document(lease,app,'part.SLDPRT')
            self.assertEqual(app.closed,[]);self.assertTrue(life.alive)
        self.run_owned(exercise)
    def test_foreign_document_blocks_final_cleanup(self):
        def exercise(lease,binding,app,life):
            session.close_owned_document(lease,app,'part.SLDPRT');app.docs.append('user.SLDPRT')
            lease.keep_application_open=False;finish_owned_session(lease,binding)
            self.assertEqual(binding.cleanup_status,'left_open_for_recovery');self.assertEqual(app.exit_calls,0)
            self.assertIn('user.SLDPRT',app.docs)
        self.run_owned(exercise)
    def test_anchor_close_crash_preserves_nonzero_exit(self):
        def exercise(lease,binding,app,life):
            session.close_owned_document(lease,app,'part.SLDPRT');lease.keep_application_open=False
            finish_owned_session(lease,binding)
            self.assertEqual(binding.cleanup_status,'process_exit_failed');self.assertEqual(life.code,139)
            self.assertTrue(binding.cleanup_error)
        self.run_owned(exercise,exit_code=139)
    def test_disconnected_close_is_only_clean_when_proved_anchor_and_zero_exit(self):
        def exercise(lease,binding,app,life):
            session.close_owned_document(lease,app,'part.SLDPRT');lease.keep_application_open=False
            finish_owned_session(lease,binding)
            self.assertEqual(binding.cleanup_status,'process_exited_cleanly');self.assertEqual(lease.owned_docs,{})
        self.run_owned(exercise,disconnect_after_close=True)
    def test_unknown_exit_never_becomes_clean(self):
        def exercise(lease,binding,app,life):
            session.close_owned_document(lease,app,'part.SLDPRT');lease.keep_application_open=False
            finish_owned_session(lease,binding)
            self.assertEqual(binding.cleanup_status,'left_open_for_recovery');self.assertTrue(binding.cleanup_error)
        self.run_owned(exercise,exit_code=None)
    def test_bulk_close_preserves_anchor_in_owned_task(self):
        def exercise(lease,binding,app,life):
            session.close_all_documents(lease,app,list(app.docs))
            self.assertTrue(life.alive);self.assertEqual(app.docs,[lease.keepalive_document_title])
        self.run_owned(exercise)
    def test_nested_com_scope_borrows_task_initialization(self):
        def job():
            lease=session.current_lease();lease.com_initialized=True;com=MagicMock()
            self.assertFalse(session.initialize_com_scope(com,lease));com.CoInitialize.assert_not_called()
        session.run_on_task_sta(job,timeout=3,task_name='fake-com-scope')
    def test_non_task_com_scope_owns_its_extra_initialization(self):
        com=MagicMock();self.assertTrue(session.initialize_com_scope(com,None));com.CoInitialize.assert_called_once()

if __name__=='__main__':unittest.main()
