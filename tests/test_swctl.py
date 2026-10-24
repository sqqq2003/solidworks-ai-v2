"""swctl command-surface tests: every command emits one JSON document."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_swctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "swctl.py"), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class SwctlTests(unittest.TestCase):
    def test_machines_command_lists_registry(self):
        completed = run_swctl("machines")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(
            {row["id"] for row in payload["machines"]}, {"a01-gt-zx", "ql5050px"}
        )

    def test_doctor_command_reports_no_cad(self):
        completed = run_swctl("doctor")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["sw_started"])
        self.assertFalse(payload["cad_executed"])
        self.assertFalse(payload["desktop_display_tested"])
        # The executable path is host-specific (repo venv vs CI toolcache);
        # only its presence is part of the contract.
        self.assertTrue(payload["python_executable"])

    def test_unfold_command_emits_plan(self):
        completed = run_swctl(
            "unfold", "--legs", "30,40", "--thickness", "2.5",
            "--radius", "1.5", "--angle", "90", "--k", "0.33",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["cad_executed"])
        self.assertIn("flat_length_mm", payload["bend"])

    def test_numbers_command_allocates_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "numbers.json"
            first = run_swctl("numbers", "--parts", "p1", "--journal", str(journal))
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run_swctl("numbers", "--parts", "p2", "--journal", str(journal))
            payload = json.loads(second.stdout)
            self.assertEqual(payload["allocations"][0]["drawing_number"], "QL-5050PX-002")

    def test_precheck_command_reads_group_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            groups = Path(tmp) / "groups.json"
            groups.write_text(
                json.dumps(
                    {
                        "groups": [
                            {
                                "group_id": "g",
                                "components": ["a", "b"],
                                "grounded": "a",
                                "mates": [{"type": "lock", "between": ["a", "b"]}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            completed = run_swctl("precheck", "--groups", str(groups))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["total_issues"], 0)
            self.assertFalse(payload["mates_solved"])

    def test_missing_file_is_reported_as_json_error(self):
        completed = run_swctl("precheck", "--groups", "runtime/does-not-exist.json")
        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "failed")


if __name__ == "__main__":
    unittest.main()
