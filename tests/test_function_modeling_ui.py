"""Real Tk controls and worker queue, with synthetic/no native execution."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'desktop display unavailable')
class FunctionDesktopTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from parametric_modeling_ui import ParametricModelingWindow
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.directory=Path(temp.name)
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.panel=ParametricModelingWindow(self.root)
        self.panel.load_spec(ROOT/'examples/function-block.json')
        for name,value in [('length','40'),('width','30'),('height','10')]:self.panel.values[name].set(value)
        self.panel.preview_button.invoke();self.root.update()

    def test_formula_values_visible_and_edit_invalidates_review(self):
        self.assertEqual(self.panel.preview_data['plan']['values_mm']['volume'],12000)
        self.assertEqual(len(self.panel.table.get_children()),6)
        self.assertEqual(str(self.panel.save_button.cget('state')),'normal')
        self.panel.values['length'].set('60');self.root.update()
        self.assertIsNone(self.panel.preview_data);self.assertIsNone(self.panel.review_data)
        self.assertEqual(str(self.panel.execute_button.cget('state')),'disabled')

    def test_feature_preview_requires_named_confirmation_and_never_runs_cad_on_linux(self):
        template=self.directory/'empty.prtdot';template.write_bytes(b'synthetic template')
        self.panel.action_mode.set('新建零件');self.panel.template.set(str(template))
        self.panel.calculate();self.panel.prepare_button.invoke();self.root.update()
        self.assertEqual(self.panel.review_data['kind'],'generate')
        self.assertEqual(str(self.panel.execute_button.cget('state')),'disabled')
        self.panel.reviewer.set('Engineer');self.panel.review_confirmed.set(True);self.panel._buttons()
        self.assertEqual(str(self.panel.execute_button.cget('state')),'normal')
        with patch('parametric_modeling_ui.sys.platform','linux'),patch('tkinter.messagebox.showerror') as error:
            self.panel.execute_button.invoke()
        error.assert_called_once();self.assertEqual(list(self.directory.iterdir()),[template])

    def test_native_actions_remain_visible_at_minimum_window_size(self):
        self.panel.window.geometry('850x660');self.root.update()
        for page,controls in [(1,[self.panel.inspect_button]),(2,[self.panel.prepare_button,self.panel.execute_button])]:
            self.panel.tabs.select(page);self.root.update()
            top=self.panel.window.winfo_rooty();bottom=top+self.panel.window.winfo_height()
            for control in controls:
                self.assertTrue(control.winfo_ismapped())
                self.assertGreaterEqual(control.winfo_rooty(),top)
                self.assertLessEqual(control.winfo_rooty()+control.winfo_height(),bottom)
        self.assertEqual(str(self.panel.review_text.cget('state')),'disabled')

    def test_worker_posts_result_on_tk_thread_and_preserves_stale_output_notice(self):
        completed=[]
        def job():time.sleep(.12);return {'synthetic':True}
        self.panel._run('synthetic job',job,lambda result:completed.append(result))
        self.assertTrue(self.panel.busy)
        self.panel.values['length'].set('55')
        deadline=time.monotonic()+3
        while self.panel.busy and time.monotonic()<deadline:self.root.update();time.sleep(.02)
        self.assertFalse(self.panel.busy);self.assertEqual(completed,[])
        self.assertIn('发生变化',self.panel.status.get())


if __name__=='__main__':unittest.main()
