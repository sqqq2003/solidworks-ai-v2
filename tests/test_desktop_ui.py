"""Actual Tk smoke checks when a display is explicitly available; no COM."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

@unittest.skipUnless(os.environ.get('DISPLAY') or os.name=='nt','desktop display unavailable; run with a virtual display or Windows')
class DesktopUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from desktop_ui import Workbench
        self.root=tk.Tk();self.view=Workbench(self.root);self.root.update()
        self.addCleanup(self.view.close)

    def test_settings_drawer_and_relevant_parameters(self):
        self.assertFalse(self.view.settings_open)
        self.view.quick_task('sheet');self.root.update()
        self.assertTrue(self.view.settings_open);self.assertTrue(self.view.sheet_frame.winfo_ismapped())
        self.view.action.set('识别图纸');self.root.update()
        self.assertFalse(self.view.sheet_frame.winfo_ismapped())
        self.view.switch_mode('unified');self.root.update()
        self.assertFalse(self.view.native.winfo_ismapped())

    def test_instruction_creates_review_only(self):
        self.view._composer_focus();self.view.composer.insert('1.0','把这个滚筒总长度改成800 mm，轴径不变，两端安装结构不变。')
        self.view.send_instruction();self.root.update()
        self.assertEqual(self.view.last_request['parsed']['target_overall_mm'],800)
        self.assertFalse(self.view.last_request['native_write_allowed'])
        self.assertEqual(self.view.state['jobs'],[])
        self.assertEqual(len(self.view.chat_cards),2)

    def test_input_changes_clear_confirmation(self):
        self.view.confirmed.set(True);self.view.values['source'].set('changed.json')
        self.assertFalse(self.view.confirmed.get())

    def test_export_cannot_overwrite_existing_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'request.json';path.write_text('original')
            with patch('tkinter.filedialog.asksaveasfilename',return_value=str(path)),patch('tkinter.messagebox.showerror') as error:
                self.view.save_request({'native_write_allowed':False})
            error.assert_called_once();self.assertEqual(path.read_text(),'original')

    def test_native_result_does_not_discard_pending_queue(self):
        pending={'kind':'unified'};self.view.state['jobs']=[pending]
        self.view.messages.put(({'status':'review_required','native_batch':{}},None))
        self.view.poll()
        self.assertEqual(self.view.state['jobs'],[pending])

    def test_api_reply_uses_worker_and_remains_advisory(self):
        import time
        from ai_assistant import AIConfig,AssistantSession
        response={'output':[{'type':'message','content':[{'type':'output_text','text':'请先核对轴径与接口。'}]}]}
        self.view.ai_session=AssistantSession(AIConfig('fixture-model','fixture-api-key'),transport=lambda payload:response)
        self.view._composer_focus();self.view.composer.insert('1.0','核对滚筒改型')
        self.view.send_instruction()
        deadline=time.monotonic()+2
        while self.view.ai_busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(self.view.ai_busy)
        self.assertIn('待工程审核',self.view.chat_cards[-1].winfo_children()[0].cget('text'))
        self.assertEqual(self.view.state['jobs'],[])
        self.assertNotIn('fixture-api-key',self.view.report_text)

    def test_new_task_discards_late_api_reply(self):
        import time,threading
        from ai_assistant import AIConfig,AssistantSession
        entered=threading.Event();release=threading.Event()
        def fake(payload):
            entered.set();release.wait(timeout=2)
            return {'output':[{'type':'message','content':[{'type':'output_text','text':'old reply'}]}]}
        self.view.ai_session=AssistantSession(AIConfig('fixture-model','fixture-api-key'),transport=fake)
        self.view._start_ai('old request');self.assertTrue(entered.wait(timeout=1))
        self.view.new_task();release.set()
        deadline=time.monotonic()+.3
        while time.monotonic()<deadline:self.root.update();time.sleep(.01)
        self.assertEqual(self.view.chat_cards,[])
        self.assertFalse(self.view.ai_busy)
