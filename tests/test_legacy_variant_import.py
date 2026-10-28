import tempfile
import unittest
from pathlib import Path
from legacy_variant_import import read_legacy_csv


class LegacyVariantImportTest(unittest.TestCase):
    def test_values_and_empty_optional_stay_unconfirmed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'spec.csv'; p.write_text('规格名称,Length,Width,Height,RollerShort\n测试,1000,650,800,\n',encoding='utf-8')
            original=p.read_bytes(); report=read_legacy_csv(p); item=report['specs'][0]
            self.assertEqual(item['values']['Width'],650)
            self.assertNotIn('RollerShort',item['values'])
            self.assertNotIn('FootHeight',item['values'])
            self.assertFalse(item['confirmed']); self.assertEqual(p.read_bytes(),original)

    def test_duplicate_aliases_and_nan_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.csv'
            for text in ('Length,机长,Width,Height\n1,1,2,3\n','Length,Width,Height\nnan,2,3\n'):
                p.write_text(text,encoding='utf-8')
                with self.assertRaises(ValueError):read_legacy_csv(p)
