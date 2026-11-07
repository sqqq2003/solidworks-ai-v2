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

    def test_cleanup_never_calls_exitapp(self):
        source = (ROOT / "src" / "owned_document_lifetime.py").read_text(encoding="utf-8")
        self.assertNotIn("exit_owned_application", source)

        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            lease.keep_application_open = False
            lease.generation_saved = True
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 0)
            self.assertEqual(binding.cleanup_status, "left_open_keepalive")
            self.assertIsNone(binding.cleanup_error)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-no-exitapp")

    def test_saved_generation_plus_cleanup_disconnect_is_not_a_failure(self):
        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            lease.generation_saved = True
            lease.keep_application_open = False
            calls = {"n": 0}

            def dead_then(_app):
                calls["n"] += 1
                raise RuntimeError(-2147220995, "对象没有连接到服务器")

            binding.read_pid = dead_then
            binding.rediscover = lambda pid: None
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 0)
            self.assertIsNone(binding.cleanup_error)
            self.assertEqual(binding.cleanup_status, "saved_com_disconnected_after_generation")
            self.assertIn("ExitApp was not called", binding.cleanup_disconnect)
            self.assertEqual(binding.rebind_attempted, True)
            self.assertEqual(calls["n"], 1)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-saved-disconnect")

    def test_raw_com_error_on_getprocessid_is_not_a_bare_tuple(self):
        class com_error(Exception):
            pass

        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: [])
            lease = sw_session.current_lease()

            def dead(_app):
                raise com_error(-2147220995, "对象没有连接到服务器", None, None)

            binding.read_pid = dead
            with self.assertRaises(ComSessionDisconnected) as caught:
                sw_session.require_model_write(lease)
            self.assertEqual(type(caught.exception).__name__, "ComSessionDisconnected")
            self.assertNotIn("(-2147220995", str(caught.exception))
            self.assertIn("ExitApp was not called", str(caught.exception))

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-normalize-com-error")

    def test_excepinfo_objnotconnected_is_a_disconnect(self):
        class com_error(Exception):
            pass

        exc = com_error(
            -2147352567,
            "Exception occurred.",
            (0, "SldWorks", "CO_E_OBJNOTCONNECTED", None, 0, -2147220995),
            None,
        )
        self.assertTrue(sw_session.is_com_server_disconnect(exc))
        normalized = sw_session.normalize_com_disconnect(exc)
        self.assertIsInstance(normalized, ComSessionDisconnected)
        self.assertNotIn("(-2147352567", str(normalized))

    def test_one_pid_rebind_restores_the_owned_application(self):
        def job():
            life = Lifetime()
            dead = App(life)
            fresh = App(life)
            binding = self.bind(life, dead, lambda _app: [])
            lease = sw_session.current_lease()
            seen = {"apps": []}

            def read_pid(app):
                seen["apps"].append(app)
                if app is dead:
                    raise RuntimeError(-2147220995, "CO_E_OBJNOTCONNECTED")
                return life.pid

            binding.read_pid = read_pid
            binding.rediscover = lambda pid: fresh
            sw_session.require_model_write(lease)
            self.assertIs(binding.app, fresh)
            self.assertFalse(lease.writes_blocked)
            self.assertFalse(lease.disconnected)
            self.assertEqual(binding.rebind_attempted, True)
            self.assertIn(fresh, seen["apps"])

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-rebind-once")

    def test_nonzero_exit_stays_a_failure(self):
        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: list(app.docs))
            life.process.code = 139
            lease = sw_session.current_lease()
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 0)
            self.assertEqual(binding.cleanup_status, "process_exit_failed")
            self.assertIn("139", binding.cleanup_error)

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

    def test_keepalive_disconnect_after_body_does_not_fail_cleanup(self):
        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()

            def dead_pid(_app):
                raise RuntimeError(-2147220995, "对象没有连接到服务器")

            binding.read_pid = dead_pid
            self.assertTrue(lease.keep_application_open)
            finish_owned_session(lease, binding)
            self.assertEqual(binding.cleanup_status, "left_open_keepalive")
            self.assertIsNone(binding.cleanup_error)
            self.assertIn("ExitApp was not called", binding.cleanup_disconnect)
            self.assertEqual(app.exit_calls, 0)
            self.assertIsNone(binding.evidence()["cleanup_error"])
            self.assertIsNotNone(binding.evidence()["cleanup_disconnect"])

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-keepalive-disconnect")

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

    def test_saved_part_inventory_failure_is_partial_not_a_hard_failure(self):
        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: list(app.docs))
            lease = sw_session.current_lease()
            lease.generation_saved = True
            lease.generation_path = r"D:\out\shaft.SLDPRT"
            def inventory_hung(_app):
                raise RuntimeError("COM inventory hung")

            binding.list_titles = inventory_hung
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 0)
            self.assertIsNone(binding.cleanup_error)
            self.assertEqual(binding.cleanup_status, "partial_com_disconnect")
            self.assertIn("inventory", binding.cleanup_disconnect.casefold())
            self.assertNotIn("ExitApp", binding.cleanup_disconnect)
            self.assertEqual(lease.post_save_outcome, "partial_com_disconnect")
            self.assertEqual(lease.generation_path, r"D:\out\shaft.SLDPRT")

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-inventory-partial")

    def test_foreign_documents_still_fail_cleanup_after_save(self):
        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: list(app.docs))
            app.docs.append("支架.SLDPRT")
            lease = sw_session.current_lease()
            lease.generation_saved = True
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 0)
            self.assertEqual(binding.cleanup_status, "left_open_for_recovery")
            self.assertIsNotNone(binding.cleanup_error)
            self.assertIn("unowned", binding.cleanup_error.casefold())
            self.assertIsNone(lease.post_save_outcome)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-foreign-after-save")

    def test_suppress_clears_inventory_error_but_not_foreign_documents(self):
        from sw_owned_launch import suppress_saved_cleanup_error

        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: [])
            lease = sw_session.current_lease()
            lease.generation_saved = True
            binding.cleanup_status = "left_open_for_recovery"
            binding.cleanup_error = (
                "SessionOwnershipError: document inventory unavailable; refusing writes"
            )
            self.assertTrue(suppress_saved_cleanup_error(binding, lease))
            self.assertIsNone(binding.cleanup_error)
            self.assertEqual(binding.cleanup_status, "partial_com_disconnect")
            self.assertEqual(lease.post_save_outcome, "partial_com_disconnect")
            self.assertEqual(app.exit_calls, 0)

            binding.cleanup_error = (
                "SessionOwnershipError: unowned documents remain; preserve session: 支架.SLDPRT"
            )
            binding.cleanup_status = "left_open_for_recovery"
            lease.generation_saved = True
            self.assertFalse(suppress_saved_cleanup_error(binding, lease))
            self.assertIn("unowned", binding.cleanup_error.casefold())

            lease.generation_saved = False
            binding.cleanup_error = "document inventory unavailable; refusing writes"
            self.assertFalse(suppress_saved_cleanup_error(binding, lease))

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-suppress-inventory")

    def test_saved_turned_part_keeps_path_when_release_fails(self):
        import tempfile
        from types import SimpleNamespace

        from part_verification import PostSaveRebindFailed, kept_after_save_exit
        from turned_part import finish_turned_generation

        source = (ROOT / "src" / "turned_part.py").read_text(encoding="utf-8")
        self.assertNotIn('sw._com_read(model, "GetTitle")', source)
        self.assertNotIn(".ExitApp(", source)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shaft.SLDPRT"
            path.write_bytes(b"x" * 64)
            lease = SimpleNamespace(
                disconnected=False,
                post_save_outcome=None,
                generation_saved=True,
                generation_path=str(path),
            )
            kept = finish_turned_generation(
                path,
                saved=True,
                lease=lease,
                post_save_error=None,
                release_error=RuntimeError(
                    "document inventory unavailable; refusing writes"
                ),
            )
            self.assertEqual(kept, str(path))
            self.assertEqual(path.stat().st_size, 64)
            self.assertEqual(lease.post_save_outcome, "partial_com_disconnect")

            rebound = SimpleNamespace(
                disconnected=False,
                post_save_outcome=None,
                generation_saved=True,
            )
            kept_rebind = finish_turned_generation(
                path,
                saved=True,
                lease=rebound,
                post_save_error=PostSaveRebindFailed("ActiveDoc missing"),
                release_error=None,
            )
            self.assertEqual(kept_rebind, str(path))
            self.assertEqual(rebound.post_save_outcome, "partial_rebind_failed")

            missing = Path(folder) / "missing.SLDPRT"
            self.assertIsNone(
                finish_turned_generation(
                    missing,
                    saved=True,
                    lease=lease,
                    post_save_error=RuntimeError("gone"),
                    release_error=None,
                )
            )

        self.assertEqual(
            kept_after_save_exit(
                3,
                generation_saved=True,
                cleanup_status="partial_com_disconnect",
                post_save_outcome=None,
            ),
            0,
        )
        self.assertEqual(
            kept_after_save_exit(
                3,
                generation_saved=True,
                cleanup_status="left_open_keepalive",
                post_save_outcome=None,
            ),
            3,
        )
        self.assertEqual(
            kept_after_save_exit(
                1,
                generation_saved=False,
                cleanup_status="partial_com_disconnect",
                post_save_outcome="partial_com_disconnect",
            ),
            1,
        )

    def test_large_assembly_gettype_disconnect_rebinds_and_rewalks(self):
        from solidworks_generator import _list_open_document_titles

        class com_error(Exception):
            pass

        class Doc:
            def __init__(self, title, nxt, fail_type):
                self.title = title
                self.nxt = nxt
                self.fail_type = fail_type

            def GetTitle(self):
                return self.title

            def GetNext(self):
                return self.nxt

            def GetType(self):
                if self.fail_type:
                    raise com_error(
                        -2147417848,
                        "被调用的对象已与其客户端断开连接",
                        None,
                        None,
                    )
                return 2

        class WalkApp:
            def __init__(self, life, fail):
                self.life = life
                self.fail = fail
                self.exit_calls = 0

            def documents(self):
                head = None
                for index in range(85, -1, -1):
                    head = Doc(f"owned-{index}.SLDPRT", head, self.fail and index == 40)
                return head

            def GetDocumentCount(self):
                return 86

            def GetFirstDocument(self):
                return self.documents()

            def ExitApp(self):
                self.exit_calls += 1

        def job():
            life = Lifetime()
            dead = WalkApp(life, True)
            fresh = WalkApp(life, False)
            binding = self.bind(life, dead, lambda _app: [])
            lease = sw_session.current_lease()
            for index in range(86):
                lease.note_owned_document(f"owned-{index}.SLDPRT")
            binding.list_titles = _list_open_document_titles
            binding.rediscover = lambda pid: fresh
            sw_session.require_model_write(lease)
            self.assertIs(binding.app, fresh)
            self.assertFalse(lease.writes_blocked)
            self.assertFalse(lease.disconnected)
            self.assertEqual(dead.exit_calls, 0)
            self.assertEqual(fresh.exit_calls, 0)
            self.assertEqual(binding.rebind_attempted, False)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-asm-rewalk")

    def test_persistent_inventory_disconnect_is_partial_not_unavailable(self):
        class com_error(Exception):
            pass

        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: [])
            lease = sw_session.current_lease()

            def dead_walk(_app):
                raise com_error(
                    -2147417848,
                    "被调用的对象已与其客户端断开连接",
                    None,
                    None,
                )

            binding.list_titles = dead_walk
            with self.assertRaises(sw_session.InventoryWalkDisconnected) as caught:
                sw_session.require_model_write(lease)
            self.assertEqual(caught.exception.status, "partial_inventory_disconnect")
            self.assertNotIn("document inventory unavailable", str(caught.exception))
            self.assertNotIn("(-2147417848", str(caught.exception))
            self.assertIn("ExitApp was not called", str(caught.exception))
            self.assertTrue(lease.writes_blocked)
            self.assertTrue(lease.disconnected)
            self.assertEqual(app.exit_calls, 0)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-inventory-partial-status")

    def test_saved_shaft_inventory_disconnect_stays_partial(self):
        class com_error(Exception):
            pass

        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: [])
            lease = sw_session.current_lease()
            lease.generation_saved = True
            lease.generation_path = r"D:\out\shaft.SLDPRT"

            def dead_walk(_app):
                raise com_error(
                    -2147417848,
                    "被调用的对象已与其客户端断开连接",
                    None,
                    None,
                )

            binding.list_titles = dead_walk
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 0)
            self.assertIsNone(binding.cleanup_error)
            self.assertEqual(
                binding.cleanup_status,
                "saved_com_disconnected_after_generation",
            )
            self.assertIn("ExitApp was not called", binding.cleanup_disconnect)
            self.assertEqual(lease.generation_path, r"D:\out\shaft.SLDPRT")

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-shaft-inventory-walk")

    def test_recovered_walk_still_blocks_foreign_documents(self):
        from solidworks_generator import _list_open_document_titles

        class com_error(Exception):
            pass

        class Doc:
            def __init__(self, title):
                self.title = title

            def GetTitle(self):
                return self.title

            def GetNext(self):
                return None

            def GetType(self):
                return 2

        class Dead:
            def GetDocumentCount(self):
                return 1

            def GetFirstDocument(self):
                class Broken:
                    def GetTitle(self):
                        return "owned.SLDASM"

                    def GetType(self):
                        raise com_error(
                            -2147417848,
                            "被调用的对象已与其客户端断开连接",
                            None,
                            None,
                        )

                    def GetNext(self):
                        return None

                return Broken()

            def ExitApp(self):
                raise AssertionError("ExitApp")

        class Fresh:
            def GetDocumentCount(self):
                return 1

            def GetFirstDocument(self):
                return Doc("foreign.SLDASM")

            def ExitApp(self):
                raise AssertionError("ExitApp")

        def job():
            life = Lifetime()
            dead = Dead()
            fresh = Fresh()
            binding = self.bind(life, dead, lambda _app: [])
            lease = sw_session.current_lease()
            lease.note_owned_document("owned.SLDASM")
            binding.list_titles = _list_open_document_titles
            binding.rediscover = lambda pid: fresh
            with self.assertRaisesRegex(SessionOwnershipError, "unowned"):
                sw_session.require_model_write(lease)
            self.assertTrue(lease.writes_blocked)
            self.assertIs(binding.app, fresh)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-foreign-after-rewalk")

    def test_getnext_member_not_found_uses_igetnext_without_rebind(self):
        from solidworks_generator import _list_open_document_titles

        class com_error(Exception):
            pass

        class Doc:
            def __init__(self, title, nxt):
                self.title = title
                self.nxt = nxt

            def GetTitle(self):
                return self.title

            def GetNext(self):
                raise com_error(-2147352573, "找不到成员。", None, None)

            def IGetNext(self):
                return self.nxt

        second = Doc("b.SLDPRT", None)
        first = Doc("a.SLDPRT", second)

        class App:
            def GetDocumentCount(self):
                return 2

            def GetFirstDocument(self):
                return first

        self.assertEqual(_list_open_document_titles(App()), ["a.SLDPRT", "b.SLDPRT"])

    def test_getdocuments_skips_the_getnext_chain(self):
        from solidworks_generator import _list_open_document_titles

        class Doc:
            def __init__(self, title):
                self.title = title

            def GetTitle(self):
                return self.title

            def GetNext(self):
                raise AssertionError("GetNext")

        class App:
            def __init__(self):
                self.docs = (Doc("root.SLDASM"), Doc("part.SLDPRT"))

            def GetDocumentCount(self):
                return 2

            def GetDocuments(self):
                return self.docs

            def GetFirstDocument(self):
                raise AssertionError("GetFirstDocument")

        self.assertEqual(
            _list_open_document_titles(App()),
            ["root.SLDASM", "part.SLDPRT"],
        )

    def test_getnext_member_not_found_rebinds_and_rewalks(self):
        from solidworks_generator import _list_open_document_titles

        class com_error(Exception):
            pass

        class Doc:
            def __init__(self, title, nxt, fail):
                self.title = title
                self.nxt = nxt
                self.fail = fail

            def GetTitle(self):
                return self.title

            def GetNext(self):
                if self.fail:
                    raise com_error(-2147352573, "找不到成员。", None, None)
                return self.nxt

        class WalkApp:
            def __init__(self, fail):
                self.fail = fail
                self.exit_calls = 0
                tail = Doc("owned-1.SLDPRT", None, fail)
                self.head = Doc("owned-0.SLDPRT", tail, fail)

            def GetDocumentCount(self):
                return 2

            def GetFirstDocument(self):
                return self.head

            def ExitApp(self):
                self.exit_calls += 1

        def job():
            life = Lifetime()
            dead = WalkApp(True)
            fresh = WalkApp(False)
            binding = self.bind(life, dead, lambda _app: [])
            lease = sw_session.current_lease()
            lease.note_owned_document("owned-0.SLDPRT")
            lease.note_owned_document("owned-1.SLDPRT")
            binding.list_titles = _list_open_document_titles
            binding.rediscover = lambda pid: fresh
            sw_session.require_model_write(lease)
            self.assertIs(binding.app, fresh)
            self.assertFalse(lease.writes_blocked)
            self.assertFalse(lease.disconnected)
            self.assertEqual(dead.exit_calls, 0)
            self.assertEqual(fresh.exit_calls, 0)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-member-rewalk")

    def test_persistent_member_not_found_is_not_inventory_unavailable(self):
        class com_error(Exception):
            pass

        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: [])
            lease = sw_session.current_lease()

            def dead_walk(_app):
                raise com_error(-2147352573, "找不到成员。", None, None)

            binding.list_titles = dead_walk
            with self.assertRaises(sw_session.InventoryWalkDisconnected) as caught:
                sw_session.require_model_write(lease)
            self.assertEqual(caught.exception.status, "partial_inventory_disconnect")
            self.assertNotIn("document inventory unavailable", str(caught.exception))
            self.assertNotIn("(-2147352573", str(caught.exception))
            self.assertIn("ExitApp was not called", str(caught.exception))
            self.assertTrue(lease.writes_blocked)
            self.assertEqual(app.exit_calls, 0)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-member-partial")

    def test_saved_shaft_member_not_found_stays_partial(self):
        class com_error(Exception):
            pass

        def job():
            life = Lifetime()
            app = App(life)
            binding = self.bind(life, app, lambda _app: [])
            lease = sw_session.current_lease()
            lease.generation_saved = True
            lease.generation_path = r"D:\out\shaft.SLDPRT"

            def dead_walk(_app):
                raise com_error(-2147352573, "找不到成员。", None, None)

            binding.list_titles = dead_walk
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 0)
            self.assertIsNone(binding.cleanup_error)
            self.assertEqual(
                binding.cleanup_status,
                "saved_com_disconnected_after_generation",
            )
            self.assertIn("ExitApp was not called", binding.cleanup_disconnect)
            self.assertEqual(lease.generation_path, r"D:\out\shaft.SLDPRT")

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-shaft-member-walk")

    def test_drawing_references_are_owned_and_a_foreign_file_is_not(self):
        from owned_document_lifetime import classify_leased_references, OpenDocumentFact

        asm = r"C:\job\总图\FX-PX.SLDASM"
        part = r"C:\job\总图\bolt.SLDPRT"
        other = r"D:\someone\User.SLDPRT"
        drawing = OpenDocumentFact(
            "工程图1",
            "",
            ("装配", asm, "螺栓", part),
        )
        assembly = OpenDocumentFact("FX-PX.SLDASM", asm, ("螺栓", part))
        bolt = OpenDocumentFact("bolt.SLDPRT", part, ())
        stranger = OpenDocumentFact("User.SLDPRT", other, ())
        adopted = classify_leased_references(["工程图1"], [drawing, assembly, bolt])
        self.assertEqual(adopted.note_titles, ("FX-PX.SLDASM", "bolt.SLDPRT"))
        self.assertIsNone(adopted.rename)
        blocked = classify_leased_references(
            ["工程图1"], [drawing, assembly, bolt, stranger]
        )
        self.assertNotIn("User.SLDPRT", blocked.note_titles)
        self.assertIn("bolt.SLDPRT", blocked.note_titles)
        same_name = OpenDocumentFact("bolt.SLDPRT", r"D:\other\bolt.SLDPRT", ())
        missed = classify_leased_references(["工程图1"], [drawing, assembly, same_name])
        self.assertEqual(missed.note_titles, ("FX-PX.SLDASM",))

    def test_saveas_retitle_owns_the_drawing_closure_only(self):
        from owned_document_lifetime import classify_leased_references, OpenDocumentFact

        asm = r"C:\job\asm.SLDASM"
        part = r"C:\job\part.SLDPRT"
        saved = OpenDocumentFact(
            "QL-A2.SLDDRW",
            r"C:\job\QL-A2.SLDDRW",
            ("装配", asm, "零件", part),
        )
        assembly = OpenDocumentFact("asm.SLDASM", asm, ("零件", part))
        component = OpenDocumentFact("part.SLDPRT", part, ())
        decision = classify_leased_references(
            ["工程图1"], [saved, assembly, component]
        )
        self.assertEqual(decision.rename, ("工程图1", "QL-A2.SLDDRW"))
        self.assertEqual(decision.note_titles, ("asm.SLDASM", "part.SLDPRT"))
        foreign = classify_leased_references(
            ["task.SLDPRT"],
            [assembly, component],
        )
        self.assertIsNone(foreign.rename)
        self.assertEqual(foreign.note_titles, ())

    def test_referenced_children_pass_the_write_gate_and_close_with_closedoc(self):
        from solidworks_generator import _list_open_document_titles

        asm = r"C:\job\总图\FX-PX.SLDASM"
        part = r"C:\job\总图\bolt.SLDPRT"

        class Doc:
            def __init__(self, title, path, deps, nxt=None):
                self.title = title
                self.path = path
                self.deps = deps
                self.nxt = nxt

            def GetTitle(self):
                return self.title

            def GetPathName(self):
                return self.path

            def GetDependencies2(self, _traverse, _external, _virtual):
                return self.deps

            def GetNext(self):
                return self.nxt

            def GetType(self):
                return 3

        class Walk:
            def __init__(self, docs):
                self.docs = docs
                self.exit_calls = 0
                self.closed = []
                self.UserControl = False

            def GetDocumentCount(self):
                return len(self.docs)

            def GetFirstDocument(self):
                return self.docs[0] if self.docs else None

            def CloseDoc(self, title):
                self.closed.append(title)
                self.docs = [doc for doc in self.docs if doc.title != title]
                for index, doc in enumerate(self.docs):
                    doc.nxt = self.docs[index + 1] if index + 1 < len(self.docs) else None

            def ExitApp(self):
                self.exit_calls += 1

        bolt = Doc("bolt.SLDPRT", part, ())
        assembly = Doc("FX-PX.SLDASM", asm, ("螺栓", part), bolt)
        drawing = Doc("工程图1", "", ("装配", asm, "螺栓", part), assembly)

        def job():
            life = Lifetime()
            app = Walk([drawing, assembly, bolt])
            binding = self.bind(life, app, lambda _app: [])
            lease = sw_session.current_lease()
            lease.note_owned_document("工程图1")
            binding.list_titles = _list_open_document_titles
            sw_session.require_model_write(lease)
            self.assertFalse(lease.writes_blocked)
            self.assertEqual(lease.foreign_titles, set())
            self.assertIn("FX-PX.SLDASM", lease.owned_docs)
            self.assertIn("bolt.SLDPRT", lease.owned_docs)
            self.assertEqual(app.exit_calls, 0)
            finish_owned_session(lease, binding)
            self.assertEqual(app.exit_calls, 0)
            self.assertIsNone(binding.cleanup_error)
            self.assertEqual(binding.cleanup_status, "left_open_keepalive")
            self.assertCountEqual(
                app.closed, ["工程图1", "FX-PX.SLDASM", "bolt.SLDPRT"]
            )

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-drawing-refs-owned")

    def test_unreferenced_document_still_blocks_after_children_are_known(self):
        from solidworks_generator import _list_open_document_titles

        part = r"C:\job\part.SLDPRT"
        stranger = r"D:\someone\User.SLDPRT"

        class Doc:
            def __init__(self, title, path, deps, nxt=None):
                self.title = title
                self.path = path
                self.deps = deps
                self.nxt = nxt

            def GetTitle(self):
                return self.title

            def GetPathName(self):
                return self.path

            def GetDependencies2(self, _traverse, _external, _virtual):
                return self.deps

            def GetNext(self):
                return self.nxt

            def GetType(self):
                return 1

        class Walk:
            def __init__(self):
                user = Doc("User.SLDPRT", stranger, ())
                child = Doc("part.SLDPRT", part, (), user)
                self.head = Doc("工程图1", "", ("零件", part), child)
                self.exit_calls = 0

            def GetDocumentCount(self):
                return 3

            def GetFirstDocument(self):
                return self.head

            def ExitApp(self):
                self.exit_calls += 1

        def job():
            life = Lifetime()
            app = Walk()
            binding = self.bind(life, app, lambda _app: [])
            lease = sw_session.current_lease()
            lease.note_owned_document("工程图1")
            binding.list_titles = _list_open_document_titles
            with self.assertRaisesRegex(SessionOwnershipError, "unowned documents appeared"):
                sw_session.require_model_write(lease)
            self.assertTrue(lease.writes_blocked)
            self.assertIn("User.SLDPRT", lease.foreign_titles)
            self.assertNotIn("User.SLDPRT", lease.owned_docs)
            self.assertIn("part.SLDPRT", lease.owned_docs)
            self.assertEqual(app.exit_calls, 0)

        sw_session.run_on_task_sta(job, timeout=5, task_name="ddd-foreign-not-a-reference")

    def test_component_and_drawing_view_paths_count_as_references(self):
        from solidworks_generator import open_document_facts

        class Component:
            def __init__(self, path):
                self.path = path
                self.Name2 = "bolt-1"

            def GetPathName(self):
                return self.path

        class View:
            def __init__(self, path):
                self.path = path

            def GetReferencedModelName(self):
                return self.path

        class Asm:
            def __init__(self):
                self.title = "FX-PX.SLDASM"
                self.path = r"C:\job\FX-PX.SLDASM"

            def GetTitle(self):
                return self.title

            def GetPathName(self):
                return self.path

            def GetComponents(self, _top_only):
                return [Component(r"C:\job\bolt.SLDPRT")]

            def GetNext(self):
                return None

        class Drawing:
            def __init__(self, nxt):
                self.nxt = nxt

            def GetTitle(self):
                return "工程图1"

            def GetPathName(self):
                return ""

            def GetViews(self):
                return [[View(r"C:\job\FX-PX.SLDASM")]]

            def GetNext(self):
                return self.nxt

        class App:
            def __init__(self):
                self.asm = Asm()
                self.drawing = Drawing(self.asm)

            def GetDocumentCount(self):
                return 2

            def GetFirstDocument(self):
                return self.drawing

        facts = {title: tokens for title, _path, tokens in open_document_facts(App())}
        self.assertIn(r"C:\job\FX-PX.SLDASM", facts["工程图1"])
        self.assertIn(r"C:\job\bolt.SLDPRT", facts["FX-PX.SLDASM"])


class ReadOwnedInventoryTests(unittest.TestCase):
    def test_walk_drop_without_rebind_or_after_retries_is_inventory_disconnect(self):
        from owned_document_lifetime import read_owned_inventory

        class com_error(Exception):
            pass

        for label, hresult in (("disconnect", -2147417848), ("member_not_found", -2147352573)):
            def walk(_app, hresult=hresult):
                raise com_error(hresult, label, None, None)

            for mode, options in (
                ("no_rebind", {}),
                ("retries_exhausted", {"rebind": lambda: object(), "disconnect_attempts": 0}),
            ):
                with self.subTest(error=label, mode=mode):
                    with self.assertRaises(sw_session.InventoryWalkDisconnected) as caught:
                        read_owned_inventory(walk, object(), **options)
                    self.assertIsInstance(caught.exception.__cause__, com_error)
                    self.assertIn("ExitApp was not called", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
