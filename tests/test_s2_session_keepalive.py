"""Reproduce background-session exit on final CloseDoc; fake COM/process only."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import sw_session as session
from sw_owned_launch import bind_spawned
from solidworks_generator import _set_sw_automation_mode


class Lifetime:
    pid=98765
    executable='C:/fake/SLDWORKS.exe'
    alive=True
    def probe(self,pid):
        return session.ProcessProbeInfo(self.pid,True,self.executable) if self.alive else None


class BackgroundApp:
    def __init__(self,lifetime):
        self.lifetime=lifetime
        self.UserControl=False
        self.CommandInProgress=False
        self.docs=[]
        self.closed=[]
    def GetUserPreferenceStringValue(self, preference):
        return self.template
    def NewDocument(self, template, *args):
        title="owned-anchor.SLDPRT"
        self.docs.append(title)
        return SimpleNamespace(GetTitle=lambda:title,GetType=lambda:1)
    def ExitApp(self):
        self.lifetime.alive=False
    def CloseDoc(self,title):
        self.closed.append(title)
        self.docs.remove(title)
        if not self.docs and not self.UserControl:
            self.lifetime.alive=False


class S2SessionKeepaliveTests(unittest.TestCase):
    def setUp(self):
        session.reset_for_tests()
        self.addCleanup(session.reset_for_tests)

    def job(self,callback,app_class=BackgroundApp):
        def run():
            life=Lifetime(); app=app_class(life)
            temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
            template=Path(temp.name)/"part.prtdot";template.touch();app.template=str(template)
            binding=bind_spawned(life,lambda pid:app,lambda app:life.pid,lambda app:app.docs,timeout=1)
            lease=session.current_lease()
            app.docs.append('task.SLDPRT');lease.note_owned_document('task.SLDPRT')
            return callback(life,app,binding,lease)
        return session.run_on_task_sta(run,timeout=5,task_name='fake-s1-s2')

    def test_automation_then_final_document_close_keeps_same_pid_for_s2(self):
        def check(life,app,binding,lease):
            _set_sw_automation_mode(app,True)
            session.close_owned_document(lease,app,'task.SLDPRT')
            self.assertTrue(life.alive,'S2 lost its owned process after S1 CloseDoc')
            self.assertIs(app.UserControl,True)
            self.assertIs(app.CommandInProgress,True)
            binding.reconnect(lease)  # same application, no active-object takeover
            self.assertEqual(app.docs,[lease.keepalive_document_title])
            self.assertTrue(binding.anchor_created)
        self.job(check)

    def test_close_reasserts_keepalive_if_another_owned_operation_reset_mode(self):
        def check(life,app,binding,lease):
            app.UserControl=False
            session.close_owned_document(lease,app,'task.SLDPRT')
            self.assertTrue(life.alive)
        self.job(check)

    def test_noop_usercontrol_setter_blocks_before_close(self):
        class NoopApp(BackgroundApp):
            @property
            def UserControl(self):return False
            @UserControl.setter
            def UserControl(self,value):pass
        def check(life,app,binding,lease):
            with self.assertRaises(session.SessionOwnershipError):
                session.close_owned_document(lease,app,'task.SLDPRT')
            self.assertEqual(app.closed,[])
            self.assertTrue(life.alive)
        self.job(check,NoopApp)

    def test_unknown_document_is_refused_without_mode_change(self):
        def check(life,app,binding,lease):
            with self.assertRaises(session.SessionOwnershipError):
                session.close_owned_document(lease,app,'unknown.SLDPRT')
            self.assertIs(app.UserControl,False)
            self.assertEqual(app.closed,[])
        self.job(check)

    def test_final_owned_exit_still_runs_after_s2(self):
        def check(life,app,binding,lease):
            session.close_owned_document(lease,app,'task.SLDPRT')
            self.assertTrue(life.alive)
            lease.keep_application_open=False
            session.exit_owned_application(lease,app)
            self.assertFalse(life.alive)
        self.job(check)
