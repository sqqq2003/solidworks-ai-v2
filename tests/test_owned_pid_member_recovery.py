import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sw_owned_launch import OwnedBinding, _read_pid
from sw_session import ComSessionDisconnected


class OwnedPidMemberRecoveryTests(unittest.TestCase):
    def test_missing_pid_member_is_a_failed_connection_not_pid_proof(self):
        class Stale:
            def __getattr__(self, name):
                raise AttributeError('<unknown>.' + name)
        with self.assertRaises(ComSessionDisconnected):
            _read_pid(Stale())

    def test_recovery_requires_the_same_retained_process_pid(self):
        class Lease:
            poisoned = timed_out = False
            def note_bound_application(self, app):
                self.app = app
        for pid in (42, 99):
            with self.subTest(pid=pid):
                life = SimpleNamespace(pid=42, probe=lambda p: object())
                binding = OwnedBinding(life, SimpleNamespace(), _read_pid, lambda a: [])
                binding.rediscover = lambda p: SimpleNamespace(GetProcessID=pid)
                lease = Lease()
                if pid == 42:
                    self.assertEqual(binding._read_connection_or_rebind(lease), (True, 42))
                else:
                    with self.assertRaises(ComSessionDisconnected):
                        binding._read_connection_or_rebind(lease)
                    self.assertTrue(lease.writes_blocked)


if __name__ == '__main__':
    unittest.main()
