"""Worker-level cleanup error persistence without native COM."""
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ql5050px import modeling_worker

class WorkerLifecycle(unittest.TestCase):
    def test_cleanup_failure_preserves_model_and_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'output';request=Path(tmp)/'request.json';request.write_text(json.dumps({'sw_exe':'fake','template':'fake','plan':{}}))
            def fail(*args):
                root.mkdir();(root/'checkpoint.json').write_text(json.dumps({'modeling':'saved_reopened','cleanup':'owned_document_closed','worker_pid':os.getpid()}))
                error=RuntimeError('native cleanup failed');error.native_session_evidence={'cleanup_exit_code':139};raise error
            with patch.object(modeling_worker,'run_native_part',side_effect=fail),patch.object(sys,'argv',['worker',str(request),str(root)]),patch.object(modeling_worker.faulthandler,'enable'):
                with self.assertRaisesRegex(RuntimeError,'cleanup failed'):modeling_worker.main()
            record=json.loads((root/'checkpoint.json').read_text())
            self.assertEqual(record['modeling'],'saved_reopened');self.assertEqual(record['cleanup'],'needs_review')
            self.assertEqual(record['native_session_evidence']['cleanup_exit_code'],139)
    def test_existing_output_is_not_modified_when_job_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'output';root.mkdir();checkpoint=root/'checkpoint.json';checkpoint.write_text('{"keep":"original"}')
            request=Path(tmp)/'request.json';request.write_text(json.dumps({'sw_exe':'fake','template':'fake','plan':{}}))
            with patch.object(modeling_worker,'run_native_part',side_effect=FileExistsError('existing output')),patch.object(sys,'argv',['worker',str(request),str(root)]),patch.object(modeling_worker.faulthandler,'enable'):
                with self.assertRaises(FileExistsError):modeling_worker.main()
            self.assertEqual(checkpoint.read_text(),'{"keep":"original"}')

if __name__=='__main__':unittest.main()
