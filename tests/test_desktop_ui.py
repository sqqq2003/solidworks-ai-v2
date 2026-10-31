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
        self.view.switch_mode('ql5050px');self.root.update()
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
        self.view.confirmed.set(True);self.view.preserve_circle_holes.set(True)
        self.assertFalse(self.view.confirmed.get())

    def test_direct_run_preserves_existing_queue(self):
        pending={'kind':'sheet'};self.view.state['jobs']=[pending]
        with patch('tkinter.messagebox.showinfo') as info, patch.object(self.view,'start') as start:
            self.view.run_current()
        info.assert_called_once();start.assert_not_called()
        self.assertEqual(self.view.state['jobs'],[pending])

    def test_direct_run_only_starts_after_successful_validation(self):
        with patch.object(self.view,'append',return_value=False), patch.object(self.view,'start') as start:
            self.view.run_current();start.assert_not_called()
        with patch.object(self.view,'append',return_value=True), patch.object(self.view,'start') as start:
            self.view.run_current();start.assert_called_once()

    def test_analysis_summary_exposes_limits(self):
        from desktop_ui import explain_task_result
        result=explain_task_result({'status':'analyzed','events':[{'event':'analysis','profile_count':1,'bend_line_count':0}]})
        self.assertIn('候选轮廓：1',result);self.assertIn('候选折弯线：0',result);self.assertIn('尚未生成或验收',result)

    def test_analysis_warnings_are_visible(self):
        from desktop_ui import explain_task_result
        result=explain_task_result({'status':'analyzed','events':[{'event':'analysis','warnings':['折弯线需核对']}]})
        self.assertIn('折弯线需核对',result)

    def test_unverified_native_result_shows_file_and_missing_reopen(self):
        from desktop_ui import explain_task_result
        result=explain_task_result({'status':'review_required','artifact':{'path':'test.SLDPRT'},
                                    'events':[{'event':'done','reopen':None}]})
        self.assertIn('test.SLDPRT',result);self.assertIn('重开验证尚未完成',result)
        self.assertIn('不能作为生产验收',result)

    def test_environment_shows_separate_evidence_states(self):
        import tkinter as tk
        self.view.show_environment();self.root.update()
        win=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='环境与版本')
        text=next(w for w in win.winfo_children() if isinstance(w,tk.Text)).get('1.0','end')
        self.assertIn('模拟测试',text);self.assertIn('SolidWorks 实机',text)
        self.assertIn('工程验收',text);self.assertIn('未验证',text)
        self.assertIn('不代表生产放行',text)
        win.destroy()

    def test_export_cannot_overwrite_existing_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'request.json';path.write_text('original')
            with patch('tkinter.filedialog.asksaveasfilename',return_value=str(path)),patch('tkinter.messagebox.showerror') as error:
                self.view.save_request({'native_write_allowed':False})
            error.assert_called_once();self.assertEqual(path.read_text(),'original')

    def test_native_result_does_not_discard_pending_queue(self):
        pending={'kind':'ql5050px'};self.view.state['jobs']=[pending]
        self.view.messages.put(({'status':'review_required','native_batch':{}},None))
        self.view.poll()
        self.assertEqual(self.view.state['jobs'],[pending])

    def test_dxf_overview_runs_without_creating_a_cad_job(self):
        import time
        import tkinter as tk
        import ezdxf
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.dxf'
            doc=ezdxf.new();doc.units=4;doc.modelspace().add_text('参考图纸');doc.saveas(path)
            with patch('tkinter.filedialog.askopenfilename',return_value=str(path)):
                self.view.open_dxf_overview()
            window=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='DXF 图纸概览')
            widget=next(w for w in window.winfo_children() if isinstance(w,tk.Text))
            deadline=time.monotonic()+5
            while '参考图纸' not in widget.get('1.0','end') and time.monotonic()<deadline:
                self.root.update();time.sleep(.03)
            self.assertIn('参考图纸',widget.get('1.0','end'))
            self.assertIn('不能作为生产参数',widget.get('1.0','end'))
            self.assertEqual(self.view.state['jobs'],[])
            window.destroy()

    def test_batch_review_button_is_read_only(self):
        import time,tkinter as tk,ezdxf
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'plate.dxf';doc=ezdxf.new();doc.units=4
            doc.modelspace().add_lwpolyline([(0,0),(100,0),(100,40),(0,40)],close=True);doc.saveas(path)
            with patch('tkinter.filedialog.askopenfilename',return_value=str(path)):
                self.view.open_sheet_batch_review()
            win=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='钣金批量预检')
            widget=next(w for w in win.winfo_children() if isinstance(w,tk.Text));deadline=time.monotonic()+8
            while '正在检查' in widget.get('1.0','end') and time.monotonic()<deadline:
                self.root.update();time.sleep(.03)
            self.assertIn('未生成模型',widget.get('1.0','end'));self.assertEqual(self.view.state['jobs'],[])
            win.destroy()

    def test_quick_review_selects_file_once_and_never_queues_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'drawing.dxf';path.write_bytes(b'not parsed in this test')
            with patch('tkinter.filedialog.askopenfilename',return_value=str(path)) as choose, \
                 patch.object(self.view,'open_dxf_overview') as overview:
                self.view.start_dxf_review()
            choose.assert_called_once()
            overview.assert_called_once_with(str(path))
            self.assertEqual(self.view.values['source'].get(),str(path))
            self.assertEqual(self.view.action.get(),'识别图纸')
            self.assertEqual(self.view.state['jobs'],[])
            self.assertFalse(self.view.confirmed.get())

    def test_preview_layer_filter_only_changes_visual_display(self):
        import tkinter as tk
        preview={'paths':[{'layer':'a','points':[(0,0),(10,0)]},
                          {'layer':'b','points':[(0,0),(0,10)]}],
                 'omitted':{'TEXT':1},'truncated':False}
        self.view.show_dxf_preview(preview);self.root.update()
        win=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='DXF 图形预览')
        body=next(w for w in win.winfo_children() if isinstance(w,tk.Frame))
        panel=next(w for w in body.winfo_children() if isinstance(w,tk.Frame))
        canvas=next(w for w in body.winfo_children() if isinstance(w,tk.Canvas))
        listing=next(w for w in panel.winfo_children() if isinstance(w,tk.Listbox))
        listing.selection_clear(0,'end');listing.selection_set(0)
        next(w for w in panel.winfo_children() if isinstance(w,tk.Button) and w.cget('text')=='显示所选图层').invoke()
        self.assertEqual(len(canvas.find_all()),1)
        self.assertEqual(self.view.state['jobs'],[])
        win.destroy()

    def test_failed_result_explains_contour_limit_and_offers_same_file(self):
        import tkinter as tk
        source='example.dxf'
        self.view.running_jobs=[{'source':source}]
        self.view.messages.put(({'status':'failed','results':[{'status':'failed','name':'example.dxf',
            'events':[{'event':'error','message':'Contour search limit reached'}]}]},None))
        with patch.object(self.view,'open_dxf_overview') as overview:
            self.view.poll();self.root.update()
            card=self.view.chat_cards[-1]
            labels=[w.cget('text') for w in card.winfo_children() if isinstance(w,tk.Label)]
            self.assertTrue(any('无法完整识别轮廓' in label for label in labels))
            button=next(w for w in card.winfo_children() if isinstance(w,tk.Button) and w.cget('text')=='查看这张图的概览')
            button.invoke();overview.assert_called_once_with(source)
