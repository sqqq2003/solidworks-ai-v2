"""Actual Tk controls with a fake native worker, never a SolidWorks test."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]


@unittest.skipUnless(os.environ.get('DISPLAY') or sys.platform=='win32','desktop display required')
class TrialDesktopTests(unittest.TestCase):
    def test_generation_button_never_selects_or_records_visual_acceptance(self):
        import tkinter as tk
        import drawing_trial_app as app
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);request=root/'request.json';target=root/'native-out'
            request.write_text(json.dumps({'assembly':str(root/'fixture.SLDASM'),'output':str(target),
                                           'explicit_partial_model_test':True}))
            texts=[];bounds=[];real_tk=tk.Tk
            def window():
                win=real_tk()
                def capture():
                    win.update_idletasks()
                    def walk(widget):
                        for child in widget.winfo_children():
                            if child.winfo_class() in {'TCheckbutton','TButton'}:
                                text=str(child.cget('text'));texts.append(text)
                                if text=='退回修改':bounds.append((child.winfo_rooty()+child.winfo_height(),win.winfo_rooty()+win.winfo_height()))
                            walk(child)
                    walk(win)
                win.after(300,capture)
                return win
            def fake_worker(command,log):
                native=json.loads(Path(command[-1]).read_text());out=Path(native['output']);out.mkdir()
                (out/'result.json').write_text(json.dumps({'status':'completed_partial_model_trial',
                    'cells':[{'status':'pass_pending_visual'}],'components':[]}))
                return 0,None
            with patch.object(tk,'Tk',side_effect=window),patch.object(app,'run_trial_worker',side_effect=fake_worker), \
                 patch('drawing_setup.detect_drawing_resources',return_value=({'A2':'fixture.drwdot'},'fixture.bom')), \
                 patch('app_logging.bootstrap',return_value=MagicMock()),patch('app_logging.install_tk_hook'), \
                 patch.object(sys,'argv',['drawing_trial_app.py','--request',str(request),'--smoke-test']):
                app.main()
            evidence=json.loads((root/'ui-result.json').read_text())
            self.assertTrue(evidence['drawing_generated']);self.assertFalse(evidence['delivery_accepted'])
            self.assertEqual(evidence['acceptance_state'],'reviewing')
            self.assertIn('接受目视结果',texts);self.assertIn('退回修改',texts)
            self.assertEqual(len([s for s in texts if s in {'视图完整','尺寸与注解','比例正确','图框、标题栏与 BOM'}]),4)
            self.assertTrue(bounds);self.assertLessEqual(bounds[0][0],bounds[0][1])
            self.assertEqual(list(target.rglob('visual-reviews')),[])


if __name__=='__main__':unittest.main()
