"""Regression tests for the DEFAULT_BEND_K_FACTOR cleanup.

Issue #25 no-default-K rule: plate thickness t and K-factor are never
constants. Every job computes them from that job's inputs; missing inputs
mean pending_confirmation, never a default number.

PR #29 removed BendAllowanceSpec's k_factor default and the generic
material K table, but src/solidworks_generator.py still carried a dead
``DEFAULT_BEND_K_FACTOR = 0.44`` definition. This file guards that the
generator no longer defines it, that no src/ module references it, and
that bend math still requires an explicit per-job K.

These tests run on Linux without SolidWorks: they scan source text and
exercise only the pure-Python bend_allowance module. They never import
solidworks_generator (Windows/COM-bound).
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
GENERATOR_PATH = SRC_DIR / "solidworks_generator.py"

sys.path.insert(0, str(SRC_DIR))

from bend_allowance import (  # noqa: E402
    BendAllowanceSpec,
    bend_allowance_mm,
    bend_deduction_mm,
)

FORBIDDEN_IDENTIFIER = "DEFAULT_BEND_K_FACTOR"


def _read_generator_source() -> str:
    return GENERATOR_PATH.read_text(encoding="utf-8")


class TestNoGeneratorDefaultK(unittest.TestCase):
    def test_generator_defines_no_default_k_constant(self):
        """The generator source must not define DEFAULT_BEND_K_FACTOR."""
        source = _read_generator_source()
        self.assertNotIn(FORBIDDEN_IDENTIFIER, source)

    def test_generator_has_no_default_k_policy_comment(self):
        """The 'default mild-steel K=0.44' policy comment must be gone."""
        source = _read_generator_source()
        self.assertNotIn("默认按软钢", source)
        self.assertNotIn("0.44", source)

    def test_no_src_module_references_default_k_constant(self):
        """No module under src/ may reference DEFAULT_BEND_K_FACTOR."""
        offenders = []
        for path in sorted(SRC_DIR.rglob("*.py")):
            if FORBIDDEN_IDENTIFIER in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [])

    def test_missing_k_factor_raises(self):
        """BendAllowanceSpec without k_factor must fail, never default."""
        with self.assertRaises(TypeError):
            BendAllowanceSpec(mode="k_factor")

    def test_explicit_k_factor_computes(self):
        """Explicit per-job K still computes BA/BD correctly.

        Example inputs only (t=2.0, R=1.0, 90 deg, K=0.4 -- not defaults):
        BA = (pi/2) * (R + K*t) = (pi/2) * 1.8
        OSSB = (R + t) * tan(45 deg) = 3.0
        BD = 2*OSSB - BA
        """
        ba = bend_allowance_mm(2.0, 1.0, 90.0, 0.4)
        self.assertAlmostEqual(ba, (math.pi / 2.0) * 1.8, places=6)
        bd = bend_deduction_mm(2.0, 1.0, 90.0, 0.4)
        self.assertAlmostEqual(bd, 2.0 * 3.0 - ba, places=6)


if __name__ == "__main__":
    unittest.main()
