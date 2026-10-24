"""模块 ⑥ 自测（Linux 可跑，纯标准库）。

自测策略：全部用临时目录搭“假检出”（真实 unittest 文件 +
真实子进程跑），不依赖仓库真实代码；对真实检出的唯一断言
是“无默认值扫描”——扫描本包执行路径源码，确认没有给
DEFAULT_K / DEFAULT_T / MATERIAL_K_FACTORS /
DEFAULT_BEND_K_FACTOR 赋值的语句（文档数据里提及残留名不算赋值）。
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

PKG_PARENT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAKE_SUITES = [
    {
        "id": "fake-pass",
        "title": "假通过套件",
        "kind": "module",
        "target": "tests.test_fake_pass",
        "source_pr": "test",
        "source_commit": "test",
        "note": "",
    },
    {
        "id": "fake-fail",
        "title": "假失败套件",
        "kind": "module",
        "target": "tests.test_fake_fail",
        "source_pr": "test",
        "source_commit": "test",
        "note": "",
    },
    {
        "id": "fake-missing",
        "title": "假缺失套件",
        "kind": "module",
        "target": "tests.test_fake_missing",
        "source_pr": "test",
        "source_commit": "test",
        "note": "",
    },
]

FAKE_PASS_SRC = '''
import unittest


class TestFakePass(unittest.TestCase):
    def test_one(self):
        self.assertEqual(1 + 1, 2)

    def test_two(self):
        self.assertTrue(True)
'''

FAKE_FAIL_SRC = '''
import unittest


class TestFakeFail(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(1, 1)

    def test_bad(self):
        self.assertEqual(1, 2)
'''

BASELINE = {
    "fake-pass": {"expected_passed": 2},
    "fake-fail": {"expected_passed": 1},
    "fake-missing": {"expected_passed": 3},
}


def _write_fake_checkout(root):
    tests_dir = os.path.join(root, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    with open(os.path.join(tests_dir, "__init__.py"), "w") as fh:
        fh.write("")
    with open(os.path.join(tests_dir, "test_fake_pass.py"), "w") as fh:
        fh.write(FAKE_PASS_SRC)
    with open(os.path.join(tests_dir, "test_fake_fail.py"), "w") as fh:
        fh.write(FAKE_FAIL_SRC)


def _hash_tree(root):
    # 只比 .py 源码文件：子进程跑 unittest 会生成 __pycache__，
    # 那是执行副作用，不是源码修改，不计入。
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, root)] = hashlib.sha256(
                    fh.read()
                ).hexdigest()
    return out


class TestOfflineVerify(unittest.TestCase):
    def test_discover_present_and_missing(self):
        from offline_verify.runner import discover

        with tempfile.TemporaryDirectory() as root:
            _write_fake_checkout(root)
            found = discover(root, FAKE_SUITES)
            self.assertTrue(found["fake-pass"]["present"])
            self.assertTrue(found["fake-fail"]["present"])
            self.assertFalse(found["fake-missing"]["present"])

    def test_run_fake_suite_pass(self):
        from offline_verify.runner import run_suite

        with tempfile.TemporaryDirectory() as root:
            _write_fake_checkout(root)
            res = run_suite(root, FAKE_SUITES[0])
            self.assertEqual(res["status"], "pass")
            self.assertEqual(res["passed"], 2)
            self.assertEqual(res["failed"], 0)
            self.assertEqual(res["failures"], [])

    def test_run_fake_suite_fail(self):
        from offline_verify.runner import run_suite

        with tempfile.TemporaryDirectory() as root:
            _write_fake_checkout(root)
            res = run_suite(root, FAKE_SUITES[1])
            self.assertEqual(res["status"], "fail")
            self.assertEqual(res["passed"], 1)
            self.assertEqual(res["failed"], 1)
            self.assertTrue(
                any("test_bad" in name for name in res["failures"])
            )

    def test_baseline_match(self):
        from offline_verify.baseline import compare_suite

        verdict = compare_suite("fake-pass", 2, BASELINE)
        self.assertEqual(verdict["verdict"], "match")
        self.assertEqual(verdict["expected"], 2)
        self.assertEqual(verdict["delta"], 0)

    def test_baseline_diff(self):
        from offline_verify.baseline import compare_suite

        verdict = compare_suite("fake-fail", 1, BASELINE)
        # fake-fail 实际通过 1 项，但基线期望也是 1 项时应为 match；
        # 这里用 0 通过构造 diff，验证差值计算。
        self.assertEqual(verdict["verdict"], "match")
        diffed = compare_suite("fake-fail", 0, BASELINE)
        self.assertEqual(diffed["verdict"], "diff")
        self.assertEqual(diffed["delta"], -1)

    def test_missing_never_counted_as_pass(self):
        from offline_verify.runner import run_all

        with tempfile.TemporaryDirectory() as root:
            _write_fake_checkout(root)
            report = run_all(root, BASELINE, suites=FAKE_SUITES)
            missing = [s for s in report["suites"]
                       if s["id"] == "fake-missing"][0]
            self.assertEqual(missing["status"], "missing")
            self.assertEqual(missing["baseline"]["verdict"], "missing")
            self.assertNotIn("fake-missing", [
                s["id"] for s in report["suites"]
                if s["status"] == "pass"
            ])
            # 缺失套件未加 --allow-missing 时退出码为 1。
            self.assertEqual(report["exit_code"], 1)
            allowed = run_all(
                root, BASELINE, suites=FAKE_SUITES, only=["fake-pass"],
            )
            self.assertEqual(allowed["exit_code"], 0)

    def test_report_json_shape(self):
        from offline_verify.runner import run_all

        with tempfile.TemporaryDirectory() as root:
            _write_fake_checkout(root)
            report = run_all(
                root, BASELINE, suites=FAKE_SUITES, only=["fake-pass"]
            )
            for key in ("format", "suites", "summary", "missing",
                        "unregistered", "exit_code", "principles"):
                self.assertIn(key, report)
            self.assertEqual(report["format"], "offline-verify-report/1")
            self.assertIn("pending_windows_validation",
                          report["principles"])

    def test_report_markdown_shape(self):
        from offline_verify.report import render_markdown
        from offline_verify.runner import run_all

        with tempfile.TemporaryDirectory() as root:
            _write_fake_checkout(root)
            report = run_all(root, BASELINE, suites=FAKE_SUITES)
            text = render_markdown(report)
            self.assertIn("fake-pass", text)
            self.assertIn("fake-missing", text)
            self.assertIn("缺失套件", text)
            self.assertIn("汇总", text)

    def test_cli_verify_end_to_end(self):
        # CLI 永远用真实注册表（不接受 fake 套件 id），故用空检出
        # 测端到端：全部套件缺失 → 退出码 1；加 --allow-missing → 0。
        # 报告文件两种情况都必须写出。
        from offline_verify.suites import SUITES

        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "checkout")
            os.makedirs(root)
            out_dir = os.path.join(tmp, "out")
            proc = subprocess.run(
                [sys.executable, "-m", "offline_verify.cli", "verify",
                 "--root", root, "--out-dir", out_dir],
                cwd=PKG_PARENT,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertTrue(os.path.isfile(
                os.path.join(out_dir, "report.json")))
            self.assertTrue(os.path.isfile(
                os.path.join(out_dir, "report.md")))
            with open(os.path.join(out_dir, "report.json")) as fh:
                report = json.load(fh)
            self.assertEqual(report["summary"]["suites_missing"],
                             len(SUITES))
            proc = subprocess.run(
                [sys.executable, "-m", "offline_verify.cli", "verify",
                 "--root", root, "--out-dir", out_dir, "--allow-missing"],
                cwd=PKG_PARENT,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0)

    def test_cli_windows_pack(self):
        from offline_verify.windows_pack import ITEMS

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "out")
            proc = subprocess.run(
                [sys.executable, "-m", "offline_verify.cli",
                 "windows-pack", "--out-dir", out_dir],
                cwd=PKG_PARENT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0)
            path = os.path.join(out_dir, "WINDOWS_ACCEPTANCE_PACK.md")
            self.assertTrue(os.path.isfile(path))
            with open(path) as fh:
                text = fh.read()
            for marker in ("A1", "B6", "C1", "D1", "G1", "W1",
                           "pending_windows_validation"):
                self.assertIn(marker, text)
            # A8 + B5 + B5 + D5 + C5 + G4 + W10 = 42
            self.assertEqual(len(ITEMS), 42)

    def test_runner_does_not_modify_source(self):
        from offline_verify.runner import run_all

        with tempfile.TemporaryDirectory() as root:
            _write_fake_checkout(root)
            before = _hash_tree(root)
            run_all(root, BASELINE, suites=FAKE_SUITES,
                    only=["fake-pass", "fake-fail"])
            after = _hash_tree(root)
            self.assertEqual(before, after)

    def test_no_default_assignment_scan(self):
        # 执行路径源码中不得出现给默认值常量赋值的语句；
        # 文档数据里提及残留名（如 W10 行）不算赋值，故用行首锚定。
        assign_re = re.compile(
            r"^\s*(DEFAULT_K|DEFAULT_T|MATERIAL_K_FACTORS|"
            r"DEFAULT_BEND_K_FACTOR)\s*="
        )
        bad = []
        for dirpath, _dirnames, filenames in os.walk(PACKAGE_DIR):
            if "tests" in dirpath.split(os.sep):
                continue
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        if assign_re.match(line):
                            bad.append("%s: %s" % (path, line.strip()))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
