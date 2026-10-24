"""Focused fake COM contracts; not native SW validation."""
import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from ql5050px.com_selection import select_by_id
from ql5050px.staged_modeling import execute_part_job

class R2Contracts(unittest.TestCase):
    def test_selection_uses_dispatch_null_and_no_retry(self):
        calls=[]
        class Extension:
            def SelectByID2(self,*args):calls.append(args);return True
        modules={'pythoncom':SimpleNamespace(VT_DISPATCH=9),'win32com':SimpleNamespace(),
            'win32com.client':SimpleNamespace(VARIANT=lambda vt,value:('variant',vt,value))}
        with patch.dict(sys.modules,modules):
            self.assertTrue(select_by_id(Extension(),'Front Plane','PLANE'))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][7],('variant',9,None))
        self.assertEqual(calls[0][2:5],(0.0,0.0,0.0))
    def test_selection_failure_retains_method_and_cause(self):
        class Extension:
            def SelectByID2(self,*args):raise ValueError('fixture mismatch')
        modules={'pythoncom':SimpleNamespace(VT_DISPATCH=9),'win32com':SimpleNamespace(),
            'win32com.client':SimpleNamespace(VARIANT=lambda vt,value:(vt,value))}
        with patch.dict(sys.modules,modules):
            with self.assertRaisesRegex(RuntimeError,'SelectByID2 failed for PLANE Front Plane') as caught:
                select_by_id(Extension(),'Front Plane','PLANE')
        self.assertIsInstance(caught.exception.__cause__,ValueError)
    def test_feature_failure_durable_context_and_traceback(self):
        class Host:
            def preflight(self,*args):pass
            def create(self):pass
            def create_editable_feature(self,feature):raise RuntimeError('fixture feature failure')
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'part'
            result=execute_part_job({'features':[{'id':'base-sketch','kind':'sketch'}]},Host(),root)
            self.assertEqual(result['modeling'],'failed')
            self.assertEqual(result['active_feature']['id'],'base-sketch')
            rows=[json.loads(line) for line in (root/'stages.jsonl').read_text().splitlines()]
            failed=next(row for row in rows if row['phase']=='modeling')
            self.assertIn('fixture feature failure',failed['traceback'])
            self.assertEqual(failed['feature']['kind'],'sketch')
            self.assertEqual(json.loads((root/'checkpoint.json').read_text())['active_feature']['id'],'base-sketch')

if __name__=='__main__':unittest.main()
