import unittest
from src.ql5050px.drawing_trial import verify_reusable_trial_session


class TrialReuseTests(unittest.TestCase):
    def setUp(self):
        self.controller={'pid':1,'creation_filetime':101};self.process={'pid':2,'creation_filetime':202}
        self.row=dict(status='COMPLETED',session_state='RESOLVED',metadata=dict(controller=self.controller,process=self.process))
        self.probe=lambda identity: identity==self.process
    def verify(self,pids=None,documents=None):
        return verify_reusable_trial_session(self.row,[2] if pids is None else pids,[] if documents is None else documents,process_probe=self.probe)
    def test_exact_resolved_empty_session_allowed(self):self.assertEqual(self.verify(),self.process)
    def test_unknown_or_multiple_processes_rejected(self):
        for pids in ([],[3],[2,3]):
            with self.subTest(pids=pids),self.assertRaises(RuntimeError):self.verify(pids=pids)
    def test_existing_documents_are_preserved_by_refusal(self):
        with self.assertRaises(RuntimeError):self.verify(documents=['unsaved user document'])
    def test_failed_or_unresolved_receipt_rejected(self):
        self.row['status']='FAILED'
        with self.assertRaises(RuntimeError):self.verify()
        self.row['status']='COMPLETED';self.row['session_state']='OUTCOME_UNKNOWN'
        with self.assertRaises(RuntimeError):self.verify()
    def test_live_old_controller_or_reused_pid_rejected(self):
        self.probe=lambda identity:True
        with self.assertRaises(RuntimeError):self.verify()
        self.probe=lambda identity:False
        with self.assertRaises(RuntimeError):self.verify()
    def test_fingerprint_covers_new_native_layout_and_trial_code(self):
        from drawing_review import drawing_implementation_hashes
        self.assertTrue({'ql5050px/auto_layout.py','ql5050px/drawing_trial.py','part_verification.py'}<=drawing_implementation_hashes().keys())
