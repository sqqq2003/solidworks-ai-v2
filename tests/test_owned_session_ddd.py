"""DDD 2026-10-25 offline contracts: ExitApp observation and startup blanks.

Fake process and COM only. These tests do not claim a SolidWorks live pass.
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sw_session
from owned_document_lifetime import (
    DEFAULT_EXIT_POLL_SECONDS,
    finish_owned_session,
)
from sw_owned_launch import bind_spawned
from sw_session import (
    ComSessionDisconnected,
    ProcessProbeInfo,
    SessionOwnershipError,
    release_task_documents,
)


ROOT = Path(__file__).resolve().parents[1]


class Lifetime:
    pid = 47828
    executable = r"C:\Program Files\SOLIDWORKS\SLDWORKS.exe"

    def __init__(self):
        self.alive = True
        self.process = _Process()

    def probe(self, pid):
        if not self.alive or pid != self.pid:
            return None
        return ProcessProbeInfo(self.pid, True, self.executable)


class _Process:
    def __init__(self):
        self.code = None
        self.waits = []
        self.on_wait = None

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.on_wait is not None:
            return self.on_wait(timeout)
        if self.code is None:
            raise subprocess.TimeoutExpired("sldworks", timeout or 0)
        return self.code


class App:
    def __init__(self, lifetime):
        self.lifetime = lifetime
        self.docs = []
        self.closed = []
        self.exit_calls = 0
        self.UserControl = False

    def CloseDoc(self, title):
        self.closed.append(title)
        if title in self.docs:
            self.docs.remove(title)

    def ExitApp(self):
        self.exit_calls += 1


class DddOwnedSessionTests(unittest.TestCase):
    def setUp(self):
        sw_session.reset_for_tests()
        self.addCleanup(sw_session.reset_for_tests)

    def bind(self, lifetime, app, listing):
        return bind_spawned(
            lifetime,
            lambda pid: app,
            lambda _app: lifetime.pid,
            listing,
            timeout=1,
        )

    def test_exit_poll_is_longer_than_the_two_second_race(self):
        self.assertGreaterEqual(DEFAULT_EXIT_POLL_SECONDS, 20)
        source = (ROOT / "src" / "owned_document_lifetime.py").read_text(encoding="utf-8")
        self.assertNotIn("timeout=2", source)
        launch = (ROOT / "src" / "sw_owned_launch.py").read_text(encoding="utf-8")
        self.assertNotIn("taskkill", launch)
        self.assertNotIn(".kill(", launch)

    def test_keep_alive_does_not_require_exitapp(self):
        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            app.docs.append("task.SLDPRT")
            lease.note_owned_document("task.SLDPRT")
            finish_owned_session(lease, binding)
            self.assertEqual(binding.cleanup_status, "left_open_keepalive")
            self.assertIsNone(binding.cleanup_error)
            self.assertEqual(app.exit_calls, 0)
            self.assertEqual(binding.evidence()["ownership"], "spawned_pid_and_live_handle")
            self.assertEqual(
                binding.evidence()["keepalive_policy"],
                "close_doc_only_keep_alive_exit_not_required",
            )

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-keepalive")

    def test_delayed_clean_exit_after_exitapp_is_success(self):
        def job():
            life = Lifetime()
            app = App(life)

            def on_wait(timeout):
                self.assertGreaterEqual(timeout, 20)
                life.process.code = 0
                life.alive = False
                return 0

            life.process.on_wait = on_wait
            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            lease.keep_application_open = False
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 1)
            self.assertEqual(binding.cleanup_status, "process_exited_cleanly")
            self.assertIsNone(binding.cleanup_error)
            self.assertEqual(life.process.waits, [DEFAULT_EXIT_POLL_SECONDS])

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-delayed-exit")

    def test_unobserved_exit_with_empty_docs_does_not_fail_probe(self):
        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            lease.keep_application_open = False
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 1)
            self.assertEqual(binding.cleanup_status, "left_open_for_recovery")
            self.assertIsNone(binding.cleanup_error)
            self.assertGreaterEqual(life.process.waits[0], 20)
            self.assertIsNone(binding.evidence()["cleanup_exit_code"])

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-unobserved-empty")

    def test_nonzero_exit_stays_a_failure(self):
        def job():
            life = Lifetime()
            app = App(life)

            def exit_app():
                app.exit_calls += 1
                life.process.code = 139
                life.alive = False

            app.ExitApp = exit_app
            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            lease.keep_application_open = False
            finish_owned_session(lease, binding)
            self.assertEqual(binding.cleanup_status, "process_exit_failed")
            self.assertIn("139", binding.cleanup_error)
            self.assertTrue(binding.cleanup_error)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-exit-139")

    def test_startup_blank_after_claim_does_not_block_writes(self):
        def job():
            life = Lifetime()
            app = App(life)
            calls = {"n": 0}

            def listing(_app):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise SessionOwnershipError("document enumeration shorter than count")
                return list(app.docs)

            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            self.assertTrue(lease.verified_exclusive)
            app.docs.append("零件2")
            binding.list_titles = listing
            lease.list_open_titles = listing
            sw_session.require_model_write(lease)
            self.assertFalse(lease.writes_blocked)
            self.assertEqual(app.docs, [])
            self.assertIn("零件2", app.closed)
            self.assertNotIn("零件2", lease.owned_docs)
            self.assertEqual(app.exit_calls, 0)
            self.assertIs(binding.app, app)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-blank-part")

    def test_saved_or_non_blank_titles_still_block(self):
        for title in ("支架.SLDPRT", "Part1.SLDPRT", "装配体1", "user-part"):
            sw_session.reset_for_tests()
            with self.subTest(title=title):
                def job(expected=title):
                    life = Lifetime()
                    app = App(life)
                    self.bind(life, app, lambda _app: list(app.docs))
                    app.docs.append(expected)
                    with self.assertRaisesRegex(SessionOwnershipError, "unowned"):
                        sw_session.require_model_write()
                    self.assertTrue(sw_session.current_lease().writes_blocked)
                    self.assertEqual(app.closed, [])

                sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-foreign-title")

    def test_release_adopts_startup_blank_instead_of_skipping_close(self):
        def job():
            life = Lifetime()
            app = App(life)
            self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            app.docs.append("零件2")
            release_task_documents(lease, app, title="零件2", close=True)
            self.assertIn("零件2", app.closed)
            self.assertEqual(app.exit_calls, 0)
            self.assertNotIn("零件2", lease.owned_docs)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-release-blank")

    def test_disconnect_while_listing_does_not_exit(self):
        def job():
            life = Lifetime()
            app = App(life)
            self.bind(life, app, lambda _app: [])

            def listing(_app):
                raise RuntimeError(-2147220995, "对象没有连接到服务器")

            lease = sw_session.current_lease()
            lease.native_launch.list_titles = listing
            lease.list_open_titles = listing
            with self.assertRaises(ComSessionDisconnected):
                sw_session.require_model_write(lease)
            self.assertEqual(app.exit_calls, 0)
            self.assertTrue(lease.disconnected)
            self.assertTrue(lease.writes_blocked)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-list-disconnect")


if __name__ == "__main__":
    unittest.main()
