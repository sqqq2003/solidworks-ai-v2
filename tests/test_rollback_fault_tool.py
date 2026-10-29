"""Fault tool remains explicit, Windows-only and checks receipt/file evidence."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from work.verify_roller_rollback import main, verify_report
from test_cad_checkpoint import ByteDriver
from test_roller_variant import fixture
from roller_variant.execution import execute_variant


class FaultToolTests(unittest.TestCase):
    def test_linux_refuses_without_claim_or_files(self):
        with tempfile.TemporaryDirectory() as folder:
            output=io.StringIO()
            with patch('work.verify_roller_rollback.sys.platform','linux'),redirect_stdout(output):
                code=main([folder,'--sw-exe','SLDWORKS.exe','--approval-sha256','fixture','--enable-fault-injection'])
            self.assertEqual(code,1);self.assertEqual(list(Path(folder).iterdir()),[])
            self.assertIn('no cloud native pass',output.getvalue())

    def test_receipt_and_later_file_corruption_prevent_false_rollback_test_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            driver=ByteDriver(fixture());report=execute_variant(fixture(),driver,Path(folder)/'run')
            report['request_receipt']={'status':'RUNNING','session_state':'ROLLBACK_UNCONFIRMED'}
            result=verify_report(report,driver.saved)
            self.assertEqual(result['status'],'failed');self.assertIn('session_still_unresolved',result['errors'])
            report['request_receipt']={'status':'FAILED','session_state':'RESOLVED'}
            driver.path.write_bytes(b'changed after alleged verification')
            result=verify_report(report,driver.saved)
            self.assertEqual(result['status'],'failed');self.assertIn('isolated_baseline_differs',result['errors'])


if __name__=='__main__': unittest.main()
