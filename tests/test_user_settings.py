"""user_settings 的行为：容错、往返、最近文件去重与上限。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import user_settings


class UserSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.base = Path(self._directory.name)
        patcher = mock.patch.object(
            user_settings, "settings_directory", return_value=self.base
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_save_then_load_round_trip(self) -> None:
        payload = {
            "sheet": {"thickness": "1.5", "auto_bend": True},
            "window": "1200x800+10+10",
            "recent_files": ["C:/a.dxf"],
        }
        self.assertTrue(user_settings.save_settings(payload))
        self.assertEqual(user_settings.load_settings(), payload)

    def test_load_returns_empty_when_file_missing(self) -> None:
        self.assertEqual(user_settings.load_settings(), {})

    def test_load_tolerates_corrupt_file(self) -> None:
        (self.base / user_settings.SETTINGS_FILE_NAME).write_text(
            "{ not json", encoding="utf-8"
        )
        self.assertEqual(user_settings.load_settings(), {})

    def test_load_ignores_non_dict_payload(self) -> None:
        (self.base / user_settings.SETTINGS_FILE_NAME).write_text(
            json.dumps([1, 2, 3]), encoding="utf-8"
        )
        self.assertEqual(user_settings.load_settings(), {})

    def test_load_accepts_utf8_bom(self) -> None:
        """记事本 / PowerShell 写出的 JSON 带 BOM，必须照样能读。"""

        payload = {"sheet": {"thickness": "2.5"}}
        (self.base / user_settings.SETTINGS_FILE_NAME).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig"
        )
        self.assertEqual(user_settings.load_settings(), payload)

    def test_explicit_path_round_trip_does_not_touch_default_file(self) -> None:
        target = self.base / "portable" / "desktop-settings.json"
        self.assertTrue(user_settings.save_settings({"sw_exe": "C:/SW/SLDWORKS.exe"}, target))
        self.assertEqual(user_settings.load_settings(target), {"sw_exe": "C:/SW/SLDWORKS.exe"})
        self.assertFalse((self.base / user_settings.SETTINGS_FILE_NAME).exists())
        self.assertEqual(user_settings.load_settings(self.base / "missing.json"), {})

    def test_save_leaves_no_temp_files_behind(self) -> None:
        user_settings.save_settings({"a": 1})
        leftovers = list(self.base.glob("settings-*.tmp"))
        self.assertEqual(leftovers, [])

    def test_sheet_defaults_fills_missing_and_rejects_wrong_types(self) -> None:
        merged = user_settings.sheet_defaults(
            {"thickness": 1.2, "angle": "45", "auto_bend": "yes", "unknown": 1}
        )
        # 类型不对的按键保留默认值，正确的值被采纳。
        self.assertEqual(merged["thickness"], user_settings.DEFAULT_SHEET["thickness"])
        self.assertEqual(merged["angle"], "45")
        self.assertTrue(merged["auto_bend"])
        self.assertNotIn("unknown", merged)

    def test_update_recent_deduplicates_and_keeps_order(self) -> None:
        stored = {"recent_files": ["a.dxf", "b.dxf", "c.dxf"]}
        result = user_settings.update_recent(stored, "b.dxf")
        self.assertEqual(result[:3], ["b.dxf", "a.dxf", "c.dxf"])

    def test_update_recent_is_capped(self) -> None:
        stored = {"recent_files": [f"{index}.dxf" for index in range(20)]}
        result = user_settings.update_recent(stored, "new.dxf")
        self.assertEqual(len(result), user_settings.MAX_RECENT_FILES)
        self.assertEqual(result[0], "new.dxf")

    def test_recent_files_drops_missing_entries(self) -> None:
        existing = self.base / "keep.dxf"
        existing.write_text("x", encoding="utf-8")
        stored = {"recent_files": [str(existing), str(self.base / "gone.dxf")]}
        self.assertEqual(user_settings.recent_files(stored), [str(existing)])

    def test_recent_files_handles_garbage(self) -> None:
        self.assertEqual(user_settings.recent_files(None), [])
        self.assertEqual(user_settings.recent_files({"recent_files": "x"}), [])
        self.assertEqual(
            user_settings.recent_files({"recent_files": [1, None, "a.dxf"]}), []
        )


if __name__ == "__main__":
    unittest.main()
