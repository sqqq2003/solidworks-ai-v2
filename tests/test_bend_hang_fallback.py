# -*- coding: utf-8 -*-
"""Watchdog timeout must fall back to flat, not hang or skip relief forever."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "src"))


import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from solidworks_generator import (
    ComDisconnectedBendError,
    GenerationResult,
    generate_sheet_metal_with_relief_retries,
)


class ReliefRetryHangTests(unittest.TestCase):
    def test_timed_out_falls_back_to_flat(self) -> None:
        analysis = MagicMock()
        flat = GenerationResult(
            Path("flat.SLDPRT"),
            0,
            0,
            0,
            (0, 0, 0, 1, 1, 0),
            (0, 0, 0, 1, 1, 0),
            0,
            auto_bent=False,
            bend_sketch_name="折弯线_手折参考",
        )
        calls: list[bool] = []

        def fake_generate(*args, **kwargs):
            calls.append(bool(kwargs.get("auto_bend")))
            if kwargs.get("auto_bend"):
                raise ComDisconnectedBendError((0, 1), relief_step=0, timed_out=True)
            return flat

        with patch(
            "solidworks_generator.generate_sheet_metal",
            side_effect=fake_generate,
        ):
            result = generate_sheet_metal_with_relief_retries(
                analysis,
                0,
                (0, 1),
                2.0,
                1.0,
                90.0,
                "out.SLDPRT",
                auto_bend=True,
            )
        self.assertEqual(calls, [True, False])
        self.assertFalse(result.auto_bent)
        self.assertEqual(result.bend_sketch_name, "折弯线_手折参考")
        # 超时那次算第 1 次尝试，不再空转扩槽。
        self.assertEqual(result.auto_bend_attempts, 1)
        self.assertTrue(result.auto_bend_abandoned)

    def test_normal_reject_expands_then_flat(self) -> None:
        from solidworks_generator import (
            BendRejectedError,
            MAX_AUTO_BEND_ATTEMPTS,
            MAX_RELIEF_STEPS,
        )

        analysis = MagicMock()
        flat = GenerationResult(
            Path("flat.SLDPRT"),
            0,
            0,
            0,
            (0, 0, 0, 1, 1, 0),
            (0, 0, 0, 1, 1, 0),
            0,
            auto_bent=False,
            bend_sketch_name="sk",
        )
        steps: list[int] = []

        def fake_generate(*args, **kwargs):
            if not kwargs.get("auto_bend"):
                return flat
            step = int(kwargs.get("relief_step", 0))
            steps.append(step)
            raise BendRejectedError((0,), relief_step=step)

        with patch(
            "solidworks_generator.generate_sheet_metal",
            side_effect=fake_generate,
        ):
            result = generate_sheet_metal_with_relief_retries(
                analysis,
                0,
                (0,),
                2.0,
                1.0,
                90.0,
                "out.SLDPRT",
                auto_bend=True,
            )
        self.assertEqual(steps, list(range(0, MAX_RELIEF_STEPS + 1)))
        # 折弯失败最多试 3 次就出平板 + 折弯线，不反复重画零件。
        self.assertEqual(MAX_AUTO_BEND_ATTEMPTS, 3)
        self.assertEqual(len(steps), MAX_AUTO_BEND_ATTEMPTS)
        self.assertFalse(result.auto_bent)
        self.assertTrue(result.auto_bend_abandoned)
        self.assertEqual(result.auto_bend_attempts, MAX_AUTO_BEND_ATTEMPTS)
        self.assertEqual(result.bend_sketch_name, "sk")

    def test_second_attempt_success_reports_attempt_count(self) -> None:
        from solidworks_generator import BendRejectedError

        analysis = MagicMock()
        bent = GenerationResult(
            Path("bent.SLDPRT"),
            0,
            1,
            0,
            (0, 0, 0, 1, 1, 0),
            (0, 0, 0, 2, 1, 0),
            0,
            auto_bent=True,
        )
        steps: list[int] = []

        def fake_generate(*args, **kwargs):
            step = int(kwargs.get("relief_step", 0))
            steps.append(step)
            if step == 0:
                raise BendRejectedError((0,), relief_step=step)
            return bent

        with patch(
            "solidworks_generator.generate_sheet_metal",
            side_effect=fake_generate,
        ):
            result = generate_sheet_metal_with_relief_retries(
                analysis,
                0,
                (0,),
                2.0,
                1.0,
                90.0,
                "out.SLDPRT",
                auto_bend=True,
            )
        self.assertEqual(steps, [0, 1])
        self.assertTrue(result.auto_bent)
        self.assertEqual(result.auto_bend_attempts, 2)
        self.assertFalse(result.auto_bend_abandoned)

    def test_progress_reports_each_attempt(self) -> None:
        from solidworks_generator import BendRejectedError

        analysis = MagicMock()
        flat = GenerationResult(
            Path("flat.SLDPRT"),
            0,
            0,
            0,
            (0, 0, 0, 1, 1, 0),
            (0, 0, 0, 1, 1, 0),
            0,
            auto_bent=False,
            bend_sketch_name="折弯线_手折参考",
        )
        notes: list[str] = []

        def fake_generate(*args, **kwargs):
            if not kwargs.get("auto_bend"):
                return flat
            raise BendRejectedError((0,), relief_step=int(kwargs.get("relief_step", 0)))

        with patch(
            "solidworks_generator.generate_sheet_metal",
            side_effect=fake_generate,
        ):
            generate_sheet_metal_with_relief_retries(
                analysis,
                0,
                (0,),
                2.0,
                1.0,
                90.0,
                "out.SLDPRT",
                auto_bend=True,
                progress=notes.append,
            )
        attempt_notes = [note for note in notes if note.startswith("自动折弯第")]
        self.assertEqual(len(attempt_notes), 3)
        self.assertIn("第 3/3 次", attempt_notes[-1])
        self.assertTrue(any("改为出平板" in note for note in notes))


if __name__ == "__main__":
    unittest.main()
