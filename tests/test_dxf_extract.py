"""Tests for the DXF extraction module (Issue #25 expansion module 3).

Standard library only. Run from the repository root:

    python3 -m unittest discover -s tests -p "test_dxf_extract.py" -v
"""

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dxf_extract.cli import main as cli_main
from dxf_extract.dxf_parser import DxfError, extract_dxf
from dxf_extract.planner import plan_features
from dxf_extract.relations import infer_relations

EXAMPLES = Path(__file__).resolve().parent.parent / "dxf_extract" / "examples"


def _write_dxf(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _dxf_document(entities: str, insunits: int | None = 4) -> str:
    header = ""
    if insunits is not None:
        header = (
            "  9\n$INSUNITS\n 70\n"
            f"{insunits:>6}\n"
        )
    return (
        "  0\nSECTION\n  2\nHEADER\n"
        f"{header}"
        "  0\nENDSEC\n  0\nSECTION\n  2\nENTITIES\n"
        f"{entities}"
        "  0\nENDSEC\n  0\nEOF\n"
    )


def _line(layer: str, start: tuple[float, float], end: tuple[float, float]) -> str:
    return (
        "  0\nLINE\n  8\n"
        f"{layer}\n 10\n{start[0]}\n 20\n{start[1]}\n"
        f" 11\n{end[0]}\n 21\n{end[1]}\n"
    )


def _circle(layer: str, centre: tuple[float, float], radius: float) -> str:
    return (
        "  0\nCIRCLE\n  8\n"
        f"{layer}\n 10\n{centre[0]}\n 20\n{centre[1]}\n 40\n{radius}\n"
    )


class TestDxfParser(unittest.TestCase):
    def test_line_circle_arc_entities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_dxf(
                Path(tmp),
                "a.dxf",
                _dxf_document(
                    _line("OUTLINE", (0, 0), (10, 0))
                    + _circle("HOLES", (5, 5), 2.5)
                    + "  0\nARC\n  8\nOUTLINE\n 10\n20.0\n 20\n20.0\n 40\n4.0\n 50\n0.0\n 51\n90.0\n"
                ),
            )
            doc = extract_dxf(path)
        self.assertEqual(doc.units, "mm")
        by_type = [entity.type for entity in doc.entities]
        self.assertEqual(by_type, ["LINE", "CIRCLE", "ARC"])
        line = doc.entities[0].geometry or {}
        self.assertEqual(line["start"], [0.0, 0.0])
        self.assertEqual(line["end"], [10.0, 0.0])
        arc = doc.entities[2].geometry or {}
        self.assertAlmostEqual(arc["start"][0], 24.0)
        self.assertAlmostEqual(arc["start"][1], 20.0)
        self.assertAlmostEqual(arc["end"][0], 20.0)
        self.assertAlmostEqual(arc["end"][1], 24.0)

    def test_lwpolyline_bulge_becomes_arc(self) -> None:
        # Chord 20 with bulge 1.0 is a semicircle: radius 10, centre on chord.
        body = (
            "  0\nLWPOLYLINE\n  8\nOUTLINE\n 90\n     2\n 70\n     0\n"
            " 10\n0.0\n 20\n0.0\n 42\n1.0\n"
            " 10\n20.0\n 20\n0.0\n 42\n0.0\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            doc = extract_dxf(_write_dxf(Path(tmp), "b.dxf", _dxf_document(body)))
        geometry = doc.entities[0].geometry or {}
        self.assertEqual(len(geometry["segments"]), 1)
        segment = geometry["segments"][0]
        self.assertEqual(segment["kind"], "arc")
        self.assertAlmostEqual(segment["radius"], 10.0)
        self.assertAlmostEqual(segment["center"][0], 10.0)
        self.assertAlmostEqual(segment["center"][1], 0.0)

    def test_units_conversion_and_unknown_units_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inch_doc = extract_dxf(
                _write_dxf(
                    Path(tmp),
                    "inch.dxf",
                    _dxf_document(_line("0", (0, 0), (1, 0)), insunits=1),
                )
            )
            self.assertEqual(inch_doc.units, "inch")
            geometry = inch_doc.entities[0].geometry or {}
            self.assertAlmostEqual(geometry["length"], 25.4)
            unknown_doc = extract_dxf(
                _write_dxf(
                    Path(tmp),
                    "unknown.dxf",
                    _dxf_document(_line("0", (0, 0), (1, 0)), insunits=None),
                )
            )
        self.assertEqual(unknown_doc.units, "unknown")
        self.assertIn("units_unknown_pending_confirmation", unknown_doc.flags)

    def test_unsupported_entities_are_flagged_not_guessed(self) -> None:
        body = (
            "  0\nSPLINE\n  8\n0\n"
            "  0\nELLIPSE\n  8\n0\n"
            "  0\nINSERT\n  8\n0\n  2\nBLOCK_A\n 10\n0.0\n 20\n0.0\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            doc = extract_dxf(_write_dxf(Path(tmp), "c.dxf", _dxf_document(body)))
        flagged = {entity.type: entity.flags for entity in doc.entities}
        self.assertEqual(doc.entities[0].status, "flagged")
        self.assertIn("spline_not_supported_exact", flagged["SPLINE"])
        self.assertIn("ellipse_not_supported_exact", flagged["ELLIPSE"])
        self.assertIn("block_reference_not_expanded", flagged["INSERT"])

    def test_binary_dxf_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bin.dxf"
            path.write_bytes(b"  0\nSECTION\x00\n")
            with self.assertRaises(DxfError):
                extract_dxf(path)


class TestRelations(unittest.TestCase):
    def test_parallel_perpendicular_and_tangent(self) -> None:
        body = (
            _line("0", (0, 0), (100, 0))
            + _line("0", (0, 60), (100, 60))
            + _line("0", (0, 0), (0, 60))
            + _circle("0", (50, 10), 10)
        )
        with tempfile.TemporaryDirectory() as tmp:
            doc = extract_dxf(_write_dxf(Path(tmp), "r.dxf", _dxf_document(body)))
        relations = infer_relations(doc)
        kinds = {relation["kind"] for relation in relations}
        self.assertIn("parallel", kinds)
        self.assertIn("perpendicular", kinds)
        # Bottom line y=0 is tangent to the circle centred (50,10) r=10.
        self.assertIn("tangent", kinds)

    def test_dimension_linear_measurement(self) -> None:
        body = (
            "  0\nDIMENSION\n  8\nDIM\n 10\n50.0\n 20\n-10.0\n"
            " 11\n50.0\n 21\n-12.0\n 70\n     0\n 50\n0.0\n"
            " 13\n0.0\n 23\n0.0\n 14\n100.0\n 24\n0.0\n  1\n\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            doc = extract_dxf(_write_dxf(Path(tmp), "d.dxf", _dxf_document(body)))
        geometry = doc.entities[0].geometry or {}
        self.assertEqual(geometry["dim_type"], 0)
        self.assertAlmostEqual(geometry["measurement_mm"] or 0.0, 100.0)


class TestPlanner(unittest.TestCase):
    def test_rect_holes_example(self) -> None:
        doc = extract_dxf(EXAMPLES / "rect_holes.dxf")
        plan = plan_features(doc, relations=infer_relations(doc))
        types = [feature["type"] for feature in plan["features"]]
        self.assertIn("contour", types)
        self.assertEqual(types.count("hole"), 2)
        holes = [f for f in plan["features"] if f["type"] == "hole"]
        diameters = sorted(h["params"]["diameter_mm"] for h in holes)
        self.assertEqual(diameters, [10.0, 16.0])
        self.assertEqual(plan["stats"]["entity_count"], 7)

    def test_flat_pattern_bend_candidates_pending_without_job_params(self) -> None:
        doc = extract_dxf(EXAMPLES / "flat_pattern.dxf")
        plan = plan_features(doc, relations=infer_relations(doc))
        bends = [f for f in plan["features"] if f["type"] == "bend_line_candidate"]
        self.assertEqual(len(bends), 2)
        for bend in bends:
            self.assertEqual(bend["status"], "pending_confirmation")
            self.assertTrue(bend["confidence"] == "high")  # BEND layer hint
            self.assertNotIn("bend_allowance_mm", bend["params"])
        flat = [f for f in plan["features"] if f["type"] == "flat_pattern"]
        self.assertEqual(len(flat), 1)
        self.assertEqual(flat[0]["status"], "pending_confirmation")

    def test_flat_pattern_bend_numbers_with_job_params(self) -> None:
        doc = extract_dxf(EXAMPLES / "flat_pattern.dxf")
        plan = plan_features(
            doc,
            job_params={
                "thickness_mm": 2.0,
                "radius_mm": 1.0,
                "angle_degrees": 90.0,
                "k_factor": 0.4,
            },
        )
        bends = [f for f in plan["features"] if f["type"] == "bend_line_candidate"]
        self.assertTrue(all(b["status"] == "confirmed" for b in bends))
        numbers = bends[0]["params"]
        expected_ba = math.radians(90.0) * (1.0 + 0.4 * 2.0)
        self.assertAlmostEqual(numbers["bend_allowance_mm"], expected_ba)
        expected_bd = 2.0 * (1.0 + 2.0) * math.tan(math.radians(45.0)) - expected_ba
        self.assertAlmostEqual(numbers["bend_deduction_mm"], expected_bd)

    def test_ambiguous_loop_is_pending_not_guessed(self) -> None:
        # A T junction: one segment ends where two unused segments start.
        body = (
            _line("0", (0, 0), (10, 0))
            + _line("0", (10, 0), (10, 10))
            + _line("0", (10, 0), (20, 0))
        )
        with tempfile.TemporaryDirectory() as tmp:
            doc = extract_dxf(_write_dxf(Path(tmp), "t.dxf", _dxf_document(body)))
        plan = plan_features(doc)
        types = [feature["type"] for feature in plan["features"]]
        self.assertNotIn("contour", types)
        self.assertTrue(any("ambiguous_loop_vertex" in item for item in plan["pending"]))

    def test_no_default_constants_in_module_sources(self) -> None:
        root = Path(__file__).resolve().parent.parent / "dxf_extract"
        forbidden = ("DEFAULT_T", "DEFAULT_K", "MATERIAL_K_FACTORS", "k_factor=0.44")
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name} contains {token}")

    def test_cli_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            code = cli_main(
                [
                    str(EXAMPLES / "flat_pattern.dxf"),
                    "--out-dir",
                    str(out_dir),
                ]
            )
            self.assertEqual(code, 0)
            geometry = json.loads((out_dir / "geometry.json").read_text(encoding="utf-8"))
            plan = json.loads((out_dir / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(geometry["format"], "dxf-extract/1")
        entity_ids = {entity["id"] for entity in geometry["entities"]}
        for feature in plan["features"]:
            for source in feature["sources"]:
                self.assertIn(source, entity_ids)
        self.assertTrue(any(f["type"] == "flat_pattern" for f in plan["features"]))

    def test_arcs_example_dimension_check(self) -> None:
        doc = extract_dxf(EXAMPLES / "arcs_holes.dxf")
        plan = plan_features(doc, relations=infer_relations(doc))
        checks = [f for f in plan["features"] if f["type"] == "dimension_check"]
        self.assertEqual(len(checks), 1)
        self.assertAlmostEqual(checks[0]["params"]["value_mm"], 12.0)


if __name__ == "__main__":
    unittest.main()
