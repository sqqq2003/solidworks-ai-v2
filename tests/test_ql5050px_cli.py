"""Entry-point smoke tests; outputs are offline simulation artifacts only."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

import ezdxf


def run_cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONUTF8"] = "1"
    return subprocess.run([sys.executable, "-m", "ql5050px", *map(str, args)],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def write_json(folder, name, payload):
    path = Path(folder) / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class CliTests(unittest.TestCase):
    def test_parameters_cli_writes_plan_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_json(folder, "parameters.json", {})
            target = Path(folder) / "plan.json"
            completed = run_cli("parameters", source, "--output", target)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            stdout = json.loads(completed.stdout)
            on_disk = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(stdout, on_disk)
            self.assertEqual(on_disk["machine"], "QL-5050PX")
            self.assertEqual(on_disk["values_mm"]["target_length"], 1800.0)
            self.assertTrue(on_disk["pending_mapping"])
            before = target.read_text(encoding="utf-8")
            second = run_cli("parameters", source, "--output", target)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_assembly_cli_reports_offline_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_json(folder, "assembly.json", {
                "components": [
                    {"id": "base", "fixed": True, "bbox_mm": [0, 0, 0, 10, 10, 10]},
                    {"id": "slide", "bbox_mm": [0, 0, 10, 5, 5, 15]},
                ],
                "mates": [{"a": "base", "b": "slide", "type": "coincident"}],
                "transmissions": [],
            })
            completed = run_cli("assembly", source)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["mode"], "offline_heuristic")
            self.assertEqual(report["estimated_dof"], {"base": 0, "slide": 5})
            self.assertEqual(report["native_checks"]["interference"], "unverified")

    def test_sheet_cli_writes_parseable_dxf(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_json(folder, "strip.json", {
                "legs_mm": [100, 50], "angles_deg": [90], "thickness_mm": 2,
                "radius_mm": 2, "k_factor": 0.44, "width_mm": 80,
            })
            target = Path(folder) / "blank.dxf"
            completed = run_cli("sheet", source, "--output", target)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            blank = json.loads(completed.stdout)
            self.assertEqual(blank["native_status"], "unverified")
            doc = ezdxf.readfile(target)
            self.assertEqual(len(list(doc.modelspace().query("LINE"))), 13)
            self.assertEqual(len(doc.audit().errors), 0)

    def test_bom_cli_writes_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_json(folder, "components.json", {
                "components": [
                    {"id": "a", "part_number": "QL-B", "material": "Q235", "quantity": 2},
                    {"id": "b", "part_number": "QL-A"},
                ]
            })
            target = Path(folder) / "bom.csv"
            completed = run_cli("bom", source, "--output", target)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with target.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["part_number"] for row in rows], ["QL-A", "QL-B"])
            self.assertEqual(rows[0]["material"], "pending_mapping")

    def test_unknown_module_is_usage_error(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_json(folder, "empty.json", {})
            completed = run_cli("nope", source)
            self.assertEqual(completed.returncode, 2)


class ExampleTests(unittest.TestCase):
    def test_example_produces_simulation_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "batch"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "examples" / "ql5050px_batch.py"),
                 "--output", str(target)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            for name in ("batch.json", "drawing.json", "simulation_blank.dxf",
                         "simulation_bom.csv"):
                self.assertTrue((target / name).is_file(), name)
            batch = json.loads((target / "batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["control"]["status"], "pending_mapping")
            self.assertFalse(batch["control"]["cad_executed"])
            self.assertEqual(batch["assembly"]["mode"], "offline_heuristic")
            self.assertEqual(batch["blank"]["native_status"], "unverified")
            self.assertEqual(batch["test_status"], "offline_simulation_only")
            drawing = json.loads((target / "drawing.json").read_text(encoding="utf-8"))
            self.assertEqual(drawing["native_status"], "unverified")
            doc = ezdxf.readfile(target / "simulation_blank.dxf")
            self.assertEqual({line.dxf.layer for line in doc.modelspace().query("LINE")},
                             {"CUT", "BEND"})

    def test_example_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "batch"
            target.mkdir()
            completed = subprocess.run(
                [sys.executable, str(ROOT / "examples" / "ql5050px_batch.py"),
                 "--output", str(target)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
