import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from parametric_workspace import preview_parameters,save_parameter_workspace


class ParameterWorkspaceTests(unittest.TestCase):
    def test_unknown_dimensions_stay_unknown_and_mapping_is_pending(self):
        result=preview_parameters(1800,900,1500)
        self.assertFalse(result['native_write_allowed'])
        self.assertFalse(result['cad_executed'])
        self.assertTrue(result['plan']['unresolved'])
        self.assertTrue(any(v is None for v in result['plan']['values_mm'].values()))
        self.assertTrue(all(row['status']=='pending_mapping' for row in result['mapping_template']['parameters']))

    def test_artifacts_are_bound_to_source_and_existing_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'new'
            result=preview_parameters(1800,900,1500)
            save_parameter_workspace(result,target)
            request=json.loads((target/'request.json').read_text(encoding='utf8'))
            self.assertEqual(request['review_sha256'],result['review_sha256'])
            self.assertTrue((target/'model-mapping.json').is_file())
            before=(target/'request.json').read_bytes()
            with self.assertRaises(FileExistsError):save_parameter_workspace(result,target)
            self.assertEqual(before,(target/'request.json').read_bytes())

    def test_changed_preview_or_rule_cannot_export_stale_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            result=preview_parameters(1800,900,1500)
            spec=Path(folder)/'rules.json';spec.write_text(json.dumps(result['spec_snapshot']),encoding='utf8')
            imported=preview_parameters(1900,950,1550,spec_path=spec)
            modified=copy.deepcopy(imported);modified['target_envelope_mm']['length']=1
            with self.assertRaises(ValueError):save_parameter_workspace(modified,Path(folder)/'tampered')
            spec.write_text('{}',encoding='utf8')
            with self.assertRaises(ValueError):save_parameter_workspace(imported,Path(folder)/'stale')
            self.assertFalse((Path(folder)/'tampered').exists());self.assertFalse((Path(folder)/'stale').exists())

    def test_invalid_target_is_rejected(self):
        for value in ['',0,-1,float('inf'),float('nan'),True]:
            with self.subTest(value=value),self.assertRaises(ValueError):preview_parameters(value,900,1500)


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'desktop display unavailable')
class ParametricDesktopTests(unittest.TestCase):
    def test_visible_entry_calculates_and_input_edit_invalidates_export(self):
        import tkinter as tk
        from desktop_ui import Workbench
        root=tk.Tk();view=Workbench(root);root.geometry('1080x740');root.update();self.addCleanup(view.close)
        sidebar=view.nav_buttons['parametric'].master
        for label in ['设置','运行记录']:
            button=next(w for w in sidebar.winfo_children() if isinstance(w,tk.Button) and w.cget('text')==label)
            self.assertTrue(button.winfo_ismapped(),label+' must remain visible')
        view.nav_buttons['parametric'].invoke();root.update()
        window=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='参数化建模')
        self.assertTrue(window.winfo_viewable())
        window.destroy()
        panel=view.open_parametric_modeling();root.update()
        panel.preview_button.invoke();root.update()
        self.assertIsNotNone(panel.preview_data)
        self.assertGreater(len(panel.table.get_children()),0)
        panel.values['length'].set('2000')
        self.assertIsNone(panel.preview_data)
        self.assertEqual(str(panel.save_button.cget('state')),'disabled')
        with patch('tkinter.messagebox.showerror') as error:
            panel.values['length'].set('');panel.preview_button.invoke()
        error.assert_called_once()
