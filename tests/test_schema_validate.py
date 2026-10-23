"""Schema validation: real module outputs must satisfy docs/schemas."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.schema_validate import (  # noqa: E402
    SchemaValidationError,
    load_schema,
    validate,
    validate_against_named_schema,
)
from src.sheetmetal_unfold import unfold_chain, unfold_plan  # noqa: E402


class SchemaValidatorTests(unittest.TestCase):
    def test_validator_catches_missing_required(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        with self.assertRaises(SchemaValidationError):
            validate({}, schema)

    def test_validator_catches_const_violation(self):
        schema = {"type": "object", "properties": {"cad_executed": {"type": "boolean", "const": False}}}
        with self.assertRaises(SchemaValidationError):
            validate({"cad_executed": True}, schema)

    def test_validator_accepts_type_union(self):
        schema = {"type": "object", "properties": {"thickness_mm": {"type": ["number", "null"]}}}
        validate({"thickness_mm": None}, schema)
        validate({"thickness_mm": 2.5}, schema)

    def test_unfold_plan_output_matches_schema(self):
        plan = unfold_plan(
            thickness_mm=2.5, radius_mm=1.5, angle_degrees=90.0, k_factor=0.33, legs_mm=[30.0, 40.0]
        )
        validate_against_named_schema(plan, "unfold-plan")

    def test_unfold_chain_output_matches_schema(self):
        chain = unfold_chain(
            thickness_mm=2.5, radius_mm=1.5, angle_degrees=90.0, k_factor=0.33, segments_mm=[30.0, 40.0, 50.0]
        )
        validate_against_named_schema(chain, "unfold-plan")

    def test_controlled_execution_mock_matches_schema(self):
        from src.a01_parametric.solver import solve_spec
        from src.sw_api.controlled import ExecutionRequest, run_controlled_execution

        plan = solve_spec()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "assembly.SLDASM"
            source.write_text("synthetic", encoding="utf-8")
            request = ExecutionRequest(
                source=str(source),
                destination=Path(tmp) / "trace.json",
                plan=plan,
                live=False,
            )
            report = run_controlled_execution(request)
        validate_against_named_schema(report, "controlled-execution")

    def test_bom_report_matches_schema(self):
        from src.drawing_bom import BomItem, BomReport

        report = BomReport(
            status="mock",
            items=(BomItem(1, "part.SLDPRT", 2, 2.5, "1000x400", None, "drawing annotation", None),),
        )
        validate_against_named_schema(report.to_dict(), "bom-report")

    def test_named_schema_missing_is_reported(self):
        with self.assertRaises(SchemaValidationError):
            load_schema("no-such-schema")


if __name__ == "__main__":
    unittest.main()
