"""Mate-chain pre-check: structural validation, not a mate solver."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.a01_next.mate_chain import (  # noqa: E402
    MateChainError,
    build_chain,
    precheck_assembly,
)

GROUP = {
    "group_id": "roller-bed",
    "components": ["frame", "roller-1", "roller-2"],
    "grounded": "frame",
    "mates": [
        {"type": "revolute", "between": ["frame", "roller-1"]},
        {"type": "revolute", "between": ["frame", "roller-2"]},
    ],
}


class MateChainTests(unittest.TestCase):
    def test_clean_group_has_no_issues(self):
        report = precheck_assembly([GROUP])
        row = report["groups"][0]
        self.assertEqual(row["issues"], 0)
        self.assertEqual(report["total_issues"], 0)
        self.assertFalse(report["mates_solved"])
        self.assertEqual(report["sw_live"], "not_applicable_on_linux")

    def test_isolated_component_is_flagged(self):
        group = dict(GROUP, components=GROUP["components"] + ["loose-bracket"])
        report = precheck_assembly([group])
        self.assertEqual(report["groups"][0]["isolated_components"], ["loose-bracket"])
        self.assertEqual(report["total_issues"], 1)

    def test_unknown_mate_type_is_refused_at_build_time(self):
        group = dict(GROUP, mates=[{"type": "hinge", "between": ["frame", "roller-1"]}])
        with self.assertRaises(MateChainError):
            build_chain([group])

    def test_mate_referencing_unknown_component_is_refused(self):
        group = dict(GROUP, mates=[{"type": "revolute", "between": ["frame", "ghost"]}])
        with self.assertRaises(MateChainError):
            build_chain([group])

    def test_unmodeled_mate_type_is_flagged_not_crashed(self):
        group = dict(
            GROUP,
            mates=[
                {"type": "revolute", "between": ["frame", "roller-1"]},
                {"type": "cam", "between": ["frame", "roller-2"]},
            ],
        )
        report = precheck_assembly([group])
        self.assertEqual(report["groups"][0]["unmodeled_mate_types"], ["cam"])

    def test_fastener_hole_mismatch_is_flagged(self):
        group = dict(
            GROUP,
            fasteners=[{"type": "bolt", "between": ["frame", "roller-1"], "count": 4}],
            holes=[{"component": "frame", "count": 2}],
        )
        report = precheck_assembly([group])
        findings = report["groups"][0]["fastener_findings"]
        kinds = {row["kind"] for row in findings}
        self.assertIn("holes_insufficient", kinds)
        self.assertIn("holes_unknown", kinds)

    def test_duplicate_group_id_is_refused(self):
        with self.assertRaises(MateChainError):
            build_chain([GROUP, dict(GROUP)])

    def test_grounded_component_must_exist(self):
        group = dict(GROUP, grounded="ghost")
        with self.assertRaises(MateChainError):
            build_chain([group])

    def test_empty_assembly_is_refused(self):
        with self.assertRaises(MateChainError):
            build_chain([])


if __name__ == "__main__":
    unittest.main()
