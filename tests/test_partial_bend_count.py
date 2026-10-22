# -*- coding: utf-8 -*-
"""部分折弯折不动时，bend_count 必须如实，不能把总条数当已折条数。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest
from unittest.mock import MagicMock, patch

from solidworks_generator import (
    BendRejectedError,
    _create_bends_with_fallbacks,
)


def _run(bend_indices, failing_groups, failing_single, all_ok=False):
    """按给定失败集合跑一轮折弯调度，返回真正折成的条数。"""

    all_key = tuple(bend_indices)

    def fake_create(*args, **kwargs):
        indices = args[7]  # bend_indices
        key = tuple(indices)
        # 默认让「全部同草图」这一步失败，逼出分组 + 逐条回退。
        if not all_ok and key == all_key:
            raise BendRejectedError(key, relief_step=0)
        if key in failing_groups:
            raise BendRejectedError(key, relief_step=0)
        if len(key) == 1 and key[0] in failing_single:
            raise BendRejectedError(key, relief_step=0)
        return None

    with (
        patch(
            "solidworks_generator._partition_bend_groups",
            return_value=[list(chunk) for chunk in _chunks(bend_indices)],
        ),
        patch("solidworks_generator._create_bend_feature", side_effect=fake_create),
        patch(
            "solidworks_generator._create_bend_reference_sketch",
            return_value=("折弯线_手折参考", 2),
        ),
    ):
        return _create_bends_with_fallbacks(
            MagicMock(),  # model
            MagicMock(),  # part
            MagicMock(),  # feature_manager
            MagicMock(),  # sketch_manager
            MagicMock(),  # extension
            MagicMock(),  # module
            MagicMock(),  # analysis
            tuple(bend_indices),
            (0.0, 0.0),
            2.0,
            1.0,
            90.0,
            False,
            None,
            0,
            None,
            MagicMock(),  # outer_profile
        )


def _chunks(indices, size=2):
    indices = list(indices)
    return [indices[i : i + size] for i in range(0, len(indices), size)]


class PartialBendCountTests(unittest.TestCase):
    def test_all_bends_succeed_returns_total(self) -> None:
        self.assertEqual(_run((0, 1, 2, 3), set(), set(), all_ok=True), 4)

    def test_one_group_rejected_then_single_retry_succeeds(self) -> None:
        # 第一组两条直接折成；第二组整组失败后逐条重试，两条各自成功。
        self.assertEqual(
            _run((0, 1, 2, 3), failing_groups={(2, 3)}, failing_single=set()),
            4,
        )

    def test_partial_failure_counts_only_completed(self) -> None:
        # 第二组逐条重试时 3 号仍然折不动：实际只折成 3 条。
        self.assertEqual(
            _run((0, 1, 2, 3), failing_groups={(2, 3)}, failing_single={3}),
            3,
        )

    def test_all_groups_failing_raises(self) -> None:
        with self.assertRaises(BendRejectedError):
            _run(
                (0, 1, 2, 3),
                failing_groups={(0, 1), (2, 3)},
                failing_single={0, 1, 2, 3},
            )


if __name__ == "__main__":
    unittest.main()
