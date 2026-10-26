import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'work'))
from prepare_test_batch import collect


class CollectBatchTests(unittest.TestCase):
    def test_collect_binds_preparation_not_report_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'wb';folder.mkdir()
            (folder/'synthetic-s2-100x80.dxf').write_bytes(b'fixture')
            receipt=dict(scope='synthetic_fixture_only_not_production',code_sha256='a'*64,
                source_sha256=hashlib.sha256(b'fixture').hexdigest(),parameters={'k_factor':.4},profile_index=0)
            (folder/'retest-plan.json').write_text(json.dumps(receipt),encoding='utf-8')
            (folder/'result.json').write_text('{}',encoding='utf-8')
            case=collect(root,[('WB','wb','wb/result.json')])['cases'][0]
            self.assertEqual(case['code_sha256'],'a'*64)
            self.assertEqual(case['parameters'],{'k_factor':.4})
            with self.assertRaises(ValueError):collect(root,[('WB','wb','../escape')])
            (folder/'synthetic-s2-100x80.dxf').write_bytes(b'changed')
            with self.assertRaises(ValueError):collect(root,[('WB','wb','wb/result.json')])

    def test_empty_batch_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):collect(tmp,[])
