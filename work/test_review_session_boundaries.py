"""Independent adversarial fake-session checks. Never starts or terminates CAD."""
import sys
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import sw_session as session


class FakeApp:
    def __init__(self):
        self.exited = False
        self.closed = []
        self.titles = []

    def ExitApp(self):
        self.exited = True

    def CloseDoc(self, title):
        self.closed.append(title)


def exclusive(app):
    lease = session.SessionLease(task_id='review')
    lease.bind_com_thread(threading.get_ident())
    lease.app_handle_id = id(app)
    lease.app_for_recycle = app
    lease.list_open_titles = lambda obj: list(obj.titles)
    lease.spawn_claimed = True
    lease.spawned_pid = 101
    lease.observed_pid = 101
    lease.foreign_titles_known = True
    lease.probe = lambda pid: session.ProcessProbeInfo(pid=pid, alive=True, image='SLDWORKS.exe')
    assert lease.prove_exclusive(101, lease.probe)
    return lease


class SessionBoundaryReview(unittest.TestCase):
    def test_lease_cannot_exit_different_application(self):
        owner, other = FakeApp(), FakeApp()
        lease = exclusive(owner)
        with self.assertRaises(session.SessionOwnershipError):
            session.exit_owned_application(lease, other)
        self.assertFalse(other.exited)

    def test_new_foreign_document_blocks_exit(self):
        app = FakeApp()
        lease = exclusive(app)
        app.titles.append('UserNew.SLDPRT')
        with self.assertRaises(session.SessionOwnershipError):
            session.exit_owned_application(lease, app)
        self.assertFalse(app.exited)

    def test_disconnected_session_cannot_exit(self):
        app = FakeApp()
        lease = exclusive(app)
        lease.disconnected = True
        with self.assertRaises(session.SessionOwnershipError):
            session.exit_owned_application(lease, app)
        self.assertFalse(app.exited)

    def test_closed_title_cannot_be_reused_to_close_replacement(self):
        app = FakeApp()
        lease = exclusive(app)
        lease.note_owned_document('Part1', handle_id=11)
        session.close_owned_document(lease, app, 'Part1')
        app.titles.append('Part1')  # user opens a different document with the old title
        with self.assertRaises(session.SessionOwnershipError):
            session.close_owned_document(lease, app, 'Part1')
        self.assertEqual(app.closed, ['Part1'])


if __name__ == '__main__':
    unittest.main()
