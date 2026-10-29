"""Actual Tk interactions with fake work/API calls; no CAD or provider traffic."""
import os,sys,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]

@unittest.skipUnless(os.environ.get('DISPLAY') or sys.platform=='win32','desktop display required')
class DeliveryDesktopTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root=tk.Tk();self.root.withdraw()
        self.addCleanup(self.root.destroy)
    def test_delivery_button_runs_existing_prepare_api_and_displays_result(self):
        from delivery_panel import open_delivery
        report={'status':'review_required','review_sha256':'r'*64,'pending':['real model required']}
        with patch('project_delivery.read_json',return_value={'schema_version':1}),patch('project_delivery.prepare_workflow',return_value=report) as prepare:
            win=open_delivery(self.root)
            design=win.nametowidget('pages.design')
            entries={'request':design.nametowidget('request'),'workspace':design.nametowidget('workspace'),
                     'review_sha256':next(w for w in design.winfo_children() if w.winfo_class()=='TLabelframe').nametowidget('review_sha256')}
            for name,value in [('request','request.json'),('workspace','new-workspace')]:entries[name].insert(0,value)
            frame=next(w for w in design.winfo_children() if w.winfo_class()=='TFrame')
            button=next(w for w in frame.winfo_children() if w.cget('text')=='创建方案');button.invoke()
            until=time.monotonic()+2
            while time.monotonic()<until and entries['review_sha256'].get()!='r'*64:
                self.root.update();time.sleep(.01)
            prepare.assert_called_once_with({'schema_version':1},'new-workspace')
            self.assertEqual(entries['review_sha256'].get(),'r'*64)
            win.tk.call(win.protocol('WM_DELETE_WINDOW'))
    def test_candidate_tab_passes_explicit_checksum_and_new_directory(self):
        from delivery_panel import open_delivery
        report={'status':'review_required','phase':'source_installed_runtime_required','source_files':2,'app_directory':'new/app'}
        with patch('release_install.install_kit',return_value=report) as install:
            win=open_delivery(self.root);page=win.nametowidget('pages.candidate')
            for name,value in [('kit','kit.zip'),('kit_sha256','a'*64),('install_dir','new')]:page.nametowidget(name).insert(0,value)
            controls=next(w for w in page.winfo_children() if w.winfo_class()=='TFrame')
            next(w for w in controls.winfo_children() if w.cget('text')=='解压到新目录').invoke()
            until=time.monotonic()+2
            while time.monotonic()<until and '源码已放入新目录' not in win.nametowidget('summary').get('1.0','end'):
                self.root.update();time.sleep(.01)
            install.assert_called_once_with('kit.zip','new',expected_sha256='a'*64)
            self.assertIn('源码已放入新目录',win.nametowidget('summary').get('1.0','end'))
            win.tk.call(win.protocol('WM_DELETE_WINDOW'))
    def test_stale_workspace_shows_actionable_summary(self):
        from delivery_panel import open_delivery
        report={'status':'review_required','phase':'revision_required','issues':[{'code':'implementation_changed'}]}
        with patch('project_delivery.inspect_workspace',return_value=report) as inspect:
            win=open_delivery(self.root);page=win.nametowidget('pages.design');page.nametowidget('workspace').insert(0,'old-workspace')
            controls=next(w for w in page.winfo_children() if w.winfo_class()=='TFrame')
            next(w for w in controls.winfo_children() if w.cget('text')=='检查工作区').invoke()
            until=time.monotonic()+2
            while time.monotonic()<until and '代码版本已变化' not in win.nametowidget('summary').get('1.0','end'):
                self.root.update();time.sleep(.01)
            inspect.assert_called_once_with('old-workspace')
            self.assertIn('代码版本已变化',win.nametowidget('summary').get('1.0','end'));win.tk.call(win.protocol('WM_DELETE_WINDOW'))
    def test_main_desktop_keeps_api_connection_and_new_delivery_entry(self):
        from desktop_ui import Workbench
        app=Workbench(self.root)
        self.assertTrue(callable(app.open_delivery));self.assertTrue(callable(app.configure_ai))
        app.configure_ai();self.root.update()
        self.assertTrue(any(w.winfo_class()=='Toplevel' for w in self.root.winfo_children()))
        self.root.after_cancel(app.poll_id)
    def test_stop_model_reply_works_when_composer_is_empty(self):
        from desktop_ui import Workbench
        app=Workbench(self.root);app.ai_busy=True;app.placeholder_visible=True
        app.send_instruction();self.assertTrue(app.ai_cancel.is_set())
        self.root.after_cancel(app.poll_id)

if __name__=='__main__':unittest.main()
