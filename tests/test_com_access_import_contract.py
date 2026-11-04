"""COM access imports must work independently of test collection order."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


class ImportContract(unittest.TestCase):
    def load(self, pythoncom):
        spec = importlib.util.spec_from_file_location(
            '_com_access_import_contract', ROOT / 'src/sw_compat/com_access.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'pythoncom': pythoncom}):
            spec.loader.exec_module(module)
        return module

    def test_missing_or_partial_pythoncom_uses_portable_flags(self):
        for pythoncom in [None, SimpleNamespace(VT_I4=3)]:
            with self.subTest(pythoncom=pythoncom):
                module = self.load(pythoncom)
                self.assertEqual((module.DISPATCH_METHOD, module.DISPATCH_PROPERTYGET), (1, 2))

    def test_available_flags_are_preserved(self):
        module = self.load(SimpleNamespace(DISPATCH_METHOD=101, DISPATCH_PROPERTYGET=202))
        self.assertEqual((module.DISPATCH_METHOD, module.DISPATCH_PROPERTYGET), (101, 202))


if __name__ == '__main__':
    unittest.main()
