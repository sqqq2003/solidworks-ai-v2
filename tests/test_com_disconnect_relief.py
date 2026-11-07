"""COM 断连不得跳过矩形释放槽重试。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest
from unittest.mock import MagicMock, patch

from solidworks_generator import (
    BendRejectedError,
    ComDisconnectedBendError,
    MAX_RELIEF_STEPS,
    _is_com_disconnect_error,
    _select_bend_sketch_for_feature,
    _try_insert_sheet_metal_bend,
)


class _FakeComError(Exception):
    """模拟 pywintypes.com_error。"""

    def __init__(self, hresult: int, message: str) -> None:
        super().__init__(hresult, message, None, None)


class ComDisconnectDetectTests(unittest.TestCase):
    def test_rpc_disconnected_hresult(self) -> None:
        err = _FakeComError(-2147417848, "被调用的对象已与其客户端断开连接。")
        self.assertTrue(_is_com_disconnect_error(err))

    def test_unsigned_hresult(self) -> None:
        # 0x80010108 as unsigned int
        err = _FakeComError(0x80010108, "disconnected")
        self.assertTrue(_is_com_disconnect_error(err))

    def test_wrapped_cause(self) -> None:
        inner = _FakeComError(-2147417848, "断开连接")
        outer = RuntimeError("wrap")
        outer.__cause__ = inner
        self.assertTrue(_is_com_disconnect_error(outer))

    def test_ordinary_error_not_disconnect(self) -> None:
        self.assertFalse(_is_com_disconnect_error(ValueError("轮廓无效")))
        self.assertFalse(_is_com_disconnect_error(None))


class SelectBendSketchComTests(unittest.TestCase):
    def test_select_by_id_disconnect_raises(self) -> None:
        model = MagicMock()
        extension = MagicMock()
        bend_sketch = MagicMock()
        bend_sketch.Name = "Sketch2"
        bend_sketch.GetSpecificFeature2.side_effect = RuntimeError("no segments")
        extension.SelectByID2.side_effect = _FakeComError(
            -2147417848, "被调用的对象已与其客户端断开连接。"
        )
        with self.assertRaises(_FakeComError):
            _select_bend_sketch_for_feature(model, extension, MagicMock(), bend_sketch)

    def test_select_by_id_other_error_returns_false(self) -> None:
        model = MagicMock()
        extension = MagicMock()
        bend_sketch = MagicMock()
        bend_sketch.Name = "Sketch2"
        bend_sketch.GetSpecificFeature2.side_effect = RuntimeError("no segments")
        extension.SelectByID2.side_effect = RuntimeError("other")
        self.assertFalse(
            _select_bend_sketch_for_feature(model, extension, MagicMock(), bend_sketch)
        )


class TryInsertComTests(unittest.TestCase):
    def test_disconnect_from_select_propagates(self) -> None:
        with patch(
            "solidworks_generator._select_bend_sketch_for_feature",
            side_effect=_FakeComError(-2147417848, "断开连接"),
        ):
            with self.assertRaises(_FakeComError):
                _try_insert_sheet_metal_bend(
                    MagicMock(),
                    MagicMock(),
                    MagicMock(),
                    MagicMock(),
                    MagicMock(),
                    MagicMock(),
                    (0.0, 0.0, 0.0),
                    1.57,
                    0.001,
                    False,
                    1,
                    False,
                    None,
                )


class BendRejectedSubclassTests(unittest.TestCase):
    def test_com_disconnected_is_bend_rejected(self) -> None:
        err = ComDisconnectedBendError((0, 1), relief_step=2)
        self.assertIsInstance(err, BendRejectedError)
        self.assertEqual(err.relief_step, 2)
        self.assertEqual(err.bend_indices, (0, 1))
        self.assertLessEqual(err.relief_step, MAX_RELIEF_STEPS)


if __name__ == "__main__":
    unittest.main()
