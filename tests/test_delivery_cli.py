"""CLI failure/read-only/result persistence contracts; no CAD process."""
from contextlib import redirect_stdout
import io,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from work.delivery import main

class CliTests(unittest.TestCase):
    def call(self,args):
        stream=io.StringIO()
        with redirect_stdout(stream):code=main(args)
        return code,json.loads(stream.getvalue())
    def test_broken_kit_is_json_failure_without_extracting(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'broken.zip';path.write_bytes(b'broken')
            code,result=self.call(['inspect-kit',str(path)])
            self.assertEqual(code,1);self.assertEqual(result['status'],'failed')
    def test_invalid_workspace_remains_inspectable_and_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'workflow.json';path.write_text('{}')
            code,result=self.call(['inspect-workspace',folder])
            self.assertEqual(code,1);self.assertEqual(result['phase'],'invalid_workspace');self.assertEqual(path.read_text(),'{}')
    def test_comparison_is_written_once_and_never_grants_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);report={'scope':'declared_coverage_and_file_integrity_only','results':[]}
            (root/'before.json').write_text(json.dumps(report));(root/'after.json').write_text(json.dumps(report))
            args=['compare-audits',str(root/'before.json'),str(root/'after.json'),'--out',str(root/'comparison.json')]
            code,result=self.call(args);self.assertEqual(code,3);self.assertFalse(result['manufacturing_approved'])
            original=(root/'comparison.json').read_bytes();self.assertEqual(self.call(args)[0],1)
            self.assertEqual((root/'comparison.json').read_bytes(),original)

    def test_receipt_command_preserves_unresolved_writer_and_linux_reconcile_refuses(self):
        from cad_receipts import ReceiptStore
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'state.sqlite3';store=ReceiptStore(db)
            row=store.begin(Path(folder)/'fixture.SLDPRT','r1',{'fixture':True})
            code,result=self.call(['receipts','--state-db',str(db),'--key',row['key']])
            self.assertEqual(code,3);self.assertEqual(result['receipt']['session_state'],'RUNNING')
            with patch('cad_reconcile.sys.platform','linux'):
                code,result=self.call(['reconcile','--state-db',str(db),'--key',row['key']])
            self.assertEqual(code,1);self.assertEqual(store.get(row['key'])['session_state'],'RUNNING')

if __name__=='__main__':unittest.main()
