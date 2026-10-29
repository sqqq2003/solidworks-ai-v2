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
            entries={int(w.grid_info()['row']):w for w in win.winfo_children() if w.winfo_class()=='TEntry'}
            for row,value in [(1,'request.json'),(2,'new-workspace')]:entries[row].insert(0,value)
            frame=next(w for w in win.winfo_children() if w.winfo_class()=='TFrame' and int(w.grid_info()['row'])==7)
            button=next(w for w in frame.winfo_children() if w.cget('text')=='创建方案');button.invoke()
            until=time.monotonic()+2
            while time.monotonic()<until and entries[4].get()!='r'*64:
                self.root.update();time.sleep(.01)
            prepare.assert_called_once_with({'schema_version':1},'new-workspace')
            self.assertEqual(entries[4].get(),'r'*64)
            win.after_cancel(win.tk.call('after','info')[0]);win.destroy()
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
