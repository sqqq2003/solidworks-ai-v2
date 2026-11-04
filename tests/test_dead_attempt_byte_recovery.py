import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cad_checkpoint import create_checkpoint,digest_file
from cad_receipts import ReceiptStore,ReconcileRequired
from cad_reconcile import restore_dead_attempt_bytes


class DeadAttemptRecovery(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.scope=self.root/'models';self.scope.mkdir()
        self.target=self.scope/'work.SLDPRT';self.target.write_bytes(b'baseline')
        self.original=self.root/'original.prtdot';self.original.write_bytes(b'original')
        self.originals={str(self.original):digest_file(self.original)}
        self.cp=create_checkpoint([self.target],self.root/'checkpoint',scope=self.scope,
            snapshot={'features':[],'bodies':[]},originals=self.originals)
        self.store=ReceiptStore(self.root/'state.sqlite3')
        self.row=self.store.begin(self.original,'baseline',{},metadata={
            'controller':{'pid':11,'creation_filetime':1},'process':{'pid':22,'creation_filetime':2},
            'original_sha256':self.originals,
            'checkpoint':{'directory':str(self.cp.directory),'manifest_sha256':self.cp.manifest_sha256,'scope':str(self.scope)}})
        self.target.write_bytes(b'preserve this failed model')

    def recover(self,alive=False):
        with patch('cad_reconcile.sys.platform','win32'),patch('cad_reconcile.process_still_matches',return_value=alive), \
             patch('sw_owned_launch._snapshot_sldworks_pids',return_value=[]):
            return restore_dead_attempt_bytes(self.row['key'],state_db=self.store.path)

    def test_dead_attempt_restores_bytes_preserves_output_and_never_claims_native_reopen(self):
        result=self.recover()
        self.assertEqual(self.target.read_bytes(),b'baseline')
        proof=result['result']['proof']
        self.assertTrue(proof['baseline_bytes_verified'])
        self.assertFalse(proof['native_reopen_verified'])
        retained=Path(proof['preserved_artifacts'][0]['archive'])
        self.assertEqual(retained.read_bytes(),b'preserve this failed model')
        self.assertEqual(self.original.read_bytes(),b'original')
        self.assertEqual((result['status'],result['session_state']),('FAILED','RESOLVED'))
        self.assertEqual(self.recover()['result'],result['result'])

    def test_live_process_or_changed_original_refuses_restoration(self):
        with self.assertRaises(ReconcileRequired):self.recover(alive=True)
        self.assertEqual(self.target.read_bytes(),b'preserve this failed model')
        self.original.write_bytes(b'changed source')
        with self.assertRaises(ReconcileRequired):self.recover()
        self.assertEqual(self.target.read_bytes(),b'preserve this failed model')
        self.assertEqual(self.store.get(self.row['key'])['session_state'],'RECOVERING')

    def test_missing_checkpoint_cannot_use_byte_restore_to_release_gate(self):
        with self.store._write() as db:
            metadata=dict(self.row['metadata']);metadata.pop('checkpoint')
            db.execute('UPDATE requests SET metadata=? WHERE key=?',(json.dumps(metadata),self.row['key']))
        with self.assertRaisesRegex(ReconcileRequired,'sealed checkpoint'):self.recover()
        self.assertEqual(self.target.read_bytes(),b'preserve this failed model')

    def test_other_solidworks_instance_blocks_byte_replacement(self):
        with patch('cad_reconcile.sys.platform','win32'),patch('cad_reconcile.process_still_matches',return_value=False), \
             patch('sw_owned_launch._snapshot_sldworks_pids',return_value=[999]):
            with self.assertRaisesRegex(ReconcileRequired,'instances still running'):
                restore_dead_attempt_bytes(self.row['key'],state_db=self.store.path)
        self.assertEqual(self.target.read_bytes(),b'preserve this failed model')
