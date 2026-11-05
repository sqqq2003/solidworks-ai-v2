import tempfile
import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from drawing_setup import drawing_defaults,detect_drawing_resources


class DrawingDefaultsTests(unittest.TestCase):
    def test_existing_context_assembly_and_executable_reuse_with_unique_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);assembly=root/'machine.SLDASM';assembly.touch()
            exe=root/'SLDWORKS.exe';exe.touch()
            settings=dict(assembly=str(assembly),sw_exe=str(exe),output_parent=str(root))
            a=drawing_defaults(settings);b=drawing_defaults(settings)
            self.assertEqual(a['models'],str(root.resolve()))
            self.assertEqual(a['assembly'],str(assembly.resolve()))
            self.assertEqual(a['sw_exe'],str(exe.resolve()))
            self.assertNotEqual(a['output'],b['output']);self.assertFalse(Path(a['output']).exists())
    def test_missing_or_wrong_paths_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'wrong.exe';file.touch()
            result=drawing_defaults(dict(assembly=str(file),sw_exe=str(file)),output_parent=folder)
            self.assertEqual(result['assembly'],'');self.assertEqual(result['sw_exe'],'')
    def test_current_assembly_wins_and_foreign_root_is_not_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=root/'old';old.mkdir();new=root/'new';new.mkdir()
            a=old/'old.SLDASM';a.touch();b=new/'new.SLDASM';b.touch()
            result=drawing_defaults(dict(models=str(old),assembly=str(a)),dict(assembly=str(b)),output_parent=root)
            self.assertEqual(result['assembly'],str(b.resolve()));self.assertEqual(result['models'],str(new.resolve()))
    def test_malformed_stored_values_are_ignored(self):
        result=drawing_defaults(dict(assembly=['invalid'],sw_exe=7,models=None,output_parent={}))
        self.assertEqual(result['assembly'],'');self.assertEqual(result['sw_exe'],'')
    def test_part_context_can_be_used_for_single_part_drawing(self):
        with tempfile.TemporaryDirectory() as folder:
            part=Path(folder)/'tube.SLDPRT';part.touch()
            result=drawing_defaults({},dict(assembly=str(part)),output_parent=folder)
            self.assertEqual(result['assembly'],str(part.resolve()))
    def test_template_choice_matches_requested_sheet_and_installed_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);exe=root/'app/SLDWORKS.exe';exe.parent.mkdir();exe.touch()
            bom=exe.parent/'lang/english/bom-standard.sldbomtbt';bom.parent.mkdir(parents=True);bom.touch()
            frames=root/'data/SOLIDWORKS/SOLIDWORKS 2025/templates';frames.mkdir(parents=True)
            for name in ('gb_a2.drwdot','gb_a3.drwdot'):(frames/name).touch()
            api=SimpleNamespace(GetFileVersionInfo=lambda *args:{'FileVersionMS':33<<16})
            with patch.dict(os.environ,PROGRAMDATA=str(root/'data')),patch.dict('sys.modules',win32api=api):
                templates,_=detect_drawing_resources(exe,sheets=('A3',))
                self.assertEqual(templates,{'A3':str(frames/'gb_a3.drwdot')})
                (frames/'gb_a3.drwdot').unlink()
                with self.assertRaises(ValueError):detect_drawing_resources(exe,sheets=('A3',))
