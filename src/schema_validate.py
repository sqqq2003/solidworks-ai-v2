"""Minimal JSON Schema validator for the offline module outputs.

Supports the subset used by ``docs/schemas/``: type (including unions),
required, properties, items, enum, const, additionalProperties. Deliberately
dependency-free so the cloud profile stays ``ezdxf``-only.
"""
from __future__ import annotations

import json
from pathlib import Path

MODULE = "issue6-schema-validate"

_SRC = Path(__file__).resolve().parent
ROOT = _SRC.parent
SCHEMA_DIR = ROOT / "docs" / "schemas"

_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


class SchemaValidationError(ValueError):
    """Raised with all collected violations for one document."""


def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise SchemaValidationError(f"schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _type_ok(value, expected) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, item) for item in expected)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    python_type = _TYPE_MAP.get(expected)
    if python_type is None:
        raise SchemaValidationError(f"unknown type in schema: {expected}")
    if python_type is bool:
        return isinstance(value, bool)
    if python_type is dict:
        return isinstance(value, dict)
    if python_type is list:
        return isinstance(value, list)
    if python_type is str:
        return isinstance(value, str)
    return isinstance(value, python_type) and not isinstance(value, bool)


def _validate(value, schema: dict, path: str, errors: list[str]) -> None:
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum {schema['enum']}")
    if "type" in schema and not _type_ok(value, schema["type"]):
        errors.append(f"{path}: expected type {schema['type']}, got {type(value).__name__}")
        return
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                _validate(item, properties[key], f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")
    elif isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]", errors)


def validate(value, schema: dict, *, name: str = "document") -> None:
    """Raise SchemaValidationError listing every violation, or return quietly."""
    errors: list[str] = []
    _validate(value, schema, name, errors)
    if errors:
        raise SchemaValidationError("; ".join(errors))


def validate_against_named_schema(value, name: str) -> None:
    validate(value, load_schema(name), name=name)
