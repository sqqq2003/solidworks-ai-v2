
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))
import logging
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import logging_setup


class LogPathTests(unittest.TestCase):
    def test_log_path_follows_local_app_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                expected = (
                    Path(tmp)
                    / logging_setup.APP_FOLDER_NAME
                    / logging_setup.LOG_FOLDER_NAME
                    / logging_setup.LOG_FILE_NAME
                )
                self.assertEqual(logging_setup.log_file_path(), expected)
                self.assertEqual(logging_setup.log_directory(), expected.parent)

    def test_falls_back_to_appdata_when_local_app_data_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"APPDATA": tmp}, clear=True):
                expected = (
                    Path(tmp)
                    / logging_setup.APP_FOLDER_NAME
                    / logging_setup.LOG_FOLDER_NAME
                )
                self.assertEqual(logging_setup.log_directory(), expected)

    def test_falls_back_without_windows_variables(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            # 取不到用户目录时也必须能给出一个可用路径，而不是抛异常。
            directory = logging_setup.log_directory()
            self.assertEqual(directory.name, logging_setup.LOG_FOLDER_NAME)
            self.assertEqual(directory.parent.name, logging_setup.APP_FOLDER_NAME)


class ConfigureLoggingTests(unittest.TestCase):
    def _temporary_log_directory(self) -> str:
        path = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        self.addCleanup(logging_setup.shutdown_logging)
        return path

    def test_writes_records_to_file_and_reuses_configuration(self) -> None:
        tmp = self._temporary_log_directory()
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            path = logging_setup.configure_logging()

            self.assertIsNotNone(path)
            assert path is not None
            logging.getLogger("test_logging_setup").warning("测试写入 %s", "内容")

            self.assertTrue(path.is_file())
            self.assertIn("测试写入 内容", path.read_text(encoding="utf-8"))
            self.assertEqual(logging_setup.configure_logging(), path)

    def test_reconfigures_when_log_directory_changes(self) -> None:
        first = self._temporary_log_directory()
        second = self._temporary_log_directory()

        with mock.patch.dict(os.environ, {"LOCALAPPDATA": first}):
            first_path = logging_setup.configure_logging()
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": second}):
            second_path = logging_setup.configure_logging()
            logging.getLogger("test_logging_setup").warning("第二个日志目录")

        self.assertNotEqual(first_path, second_path)
        self.assertIsNotNone(second_path)
        assert second_path is not None
        self.assertTrue(second_path.is_file())
        self.assertIn("第二个日志目录", second_path.read_text(encoding="utf-8"))

    def test_falls_back_to_second_candidate_when_user_directory_is_blocked(self) -> None:
        blocked_root = Path(self._temporary_log_directory())
        fallback = Path(self._temporary_log_directory())
        blocked = blocked_root / logging_setup.APP_FOLDER_NAME
        blocked.write_text("这是一个文件，不是目录", encoding="utf-8")
        candidates = (
            blocked / logging_setup.LOG_FOLDER_NAME / logging_setup.LOG_FILE_NAME,
            fallback
            / logging_setup.APP_FOLDER_NAME
            / logging_setup.LOG_FOLDER_NAME
            / logging_setup.LOG_FILE_NAME,
        )

        with mock.patch.object(
            logging_setup, "_candidate_log_paths", return_value=candidates
        ):
            self.assertEqual(logging_setup.configure_logging(), candidates[1])

    def test_returns_none_when_no_candidate_is_writable(self) -> None:
        first_root = Path(self._temporary_log_directory())
        second_root = Path(self._temporary_log_directory())
        (first_root / logging_setup.APP_FOLDER_NAME).write_text(
            "这是一个文件，不是目录", encoding="utf-8"
        )
        (second_root / logging_setup.APP_FOLDER_NAME).write_text(
            "这是一个文件，不是目录", encoding="utf-8"
        )
        candidates = (
            first_root
            / logging_setup.APP_FOLDER_NAME
            / logging_setup.LOG_FOLDER_NAME
            / logging_setup.LOG_FILE_NAME,
            second_root
            / logging_setup.APP_FOLDER_NAME
            / logging_setup.LOG_FOLDER_NAME
            / logging_setup.LOG_FILE_NAME,
        )

        with mock.patch.object(
            logging_setup, "_candidate_log_paths", return_value=candidates
        ):
            self.assertIsNone(logging_setup.configure_logging())


if __name__ == "__main__":
    unittest.main()
