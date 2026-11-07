"""Mock SolidWorks adapter tests. No COM."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.a01_parametric.solver import solve_spec
from src.sw_api.apply import dry_run_apply
from src.sw_api.interface import assert_distinct_copy
from src.sw_api.mock import MockAssemblyAdapter


class MockAdapterTests(unittest.TestCase):
    def test_dry_run_skips_unresolved_and_writes_json_only(self):
        plan = solve_spec()
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "A01.dry-run.json"
            report = dry_run_apply(plan, destination)
            self.assertEqual(report["sw_live"], "not_applicable_on_linux")
            self.assertFalse(report["cad_executed"])
            self.assertEqual(report["variables_set"], ["height", "length", "width"])
            self.assertIn("chain_pitch", report["variables_skipped_unresolved"])
            self.assertTrue(destination.is_file())
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertFalse(payload["original_overwritten"])
            self.assertFalse(list(Path(folder).glob("*.sldasm")))
            self.assertFalse(list(Path(folder).glob("*.SLDPRT")))

    def test_same_path_and_cad_suffix_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "same.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                assert_distinct_copy(path, path)
            adapter = MockAssemblyAdapter()
            with self.assertRaises(ValueError):
                adapter.save_as_copy(str(path), path, {})
            with self.assertRaises(ValueError):
                adapter.save_as_copy("simulated://A01", Path(folder) / "copy.SLDASM", {})

    def test_win32_backend_does_not_import_com_at_import(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import src.sw_api.win32com_backend as backend; "
                "assert 'win32com' not in sys.modules; assert 'pythoncom' not in sys.modules; "
                "text = open('src/sw_api/win32com_backend.py', encoding='utf-8').read(); "
                "assert 'require_model_write' in text and 'SaveAs3' in text; "
                "assert 'taskkill' not in text and 'ExitApp' not in text and 'CloseAllDocuments' not in text",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
