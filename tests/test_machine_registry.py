"""Registry structure tests: no OEM value is invented or copied here."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.machine_registry import (  # noqa: E402
    MachineRegistryError,
    get_machine,
    list_machines,
    load_machine_spec,
    load_registry,
    resolve_spec_path,
)


class RegistryTests(unittest.TestCase):
    def test_registry_lists_both_machines(self):
        rows = list_machines()
        ids = {row["id"] for row in rows}
        self.assertEqual(ids, {"a01-gt-zx", "ql5050px"})
        self.assertTrue(all(row["status"] for row in rows))

    def test_registry_entries_expose_no_dimension_values(self):
        # A registry row must not smuggle envelope or confirmed dimensions.
        for entry in load_registry()["machines"]:
            self.assertNotIn("values_mm", entry)
            self.assertNotIn("envelope_mm", entry)
            self.assertNotIn("confirmed", entry)

    def test_resolve_spec_paths_exist(self):
        for row in list_machines():
            spec = resolve_spec_path(row["id"])
            self.assertTrue(spec.is_file(), spec)
            payload = json.loads(spec.read_text(encoding="utf-8"))
            self.assertIn("machine_id", payload)

    def test_ql5050px_spec_stays_independent_of_a01(self):
        spec = load_machine_spec("ql5050px")
        self.assertEqual(spec["machine_id"], "QL-5050PX")
        self.assertIn("independent_of", spec)
        self.assertFalse(spec.get("template_identity_confirmed", False))

    def test_unknown_machine_id_is_rejected(self):
        with self.assertRaises(MachineRegistryError):
            get_machine("no-such-machine")

    def test_duplicate_ids_rejected(self):
        registry = load_registry()
        registry["machines"].append(dict(registry["machines"][0]))
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "index.json"
            broken.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaises(MachineRegistryError):
                load_registry(broken)

    def test_missing_spec_file_rejected(self):
        registry = load_registry()
        registry["machines"][0]["spec"] = "data/machines/does-not-exist.json"
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "index.json"
            broken.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaises(MachineRegistryError):
                load_registry(broken)


if __name__ == "__main__":
    unittest.main()
