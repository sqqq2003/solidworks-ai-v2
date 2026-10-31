"""Versioned real-model mapping. Unknown or protected OEM entries never write."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite


@dataclass(frozen=True)
class ParameterMapping:
    parameter: str
    document: str | None = None
    configuration: str | None = None
    feature: str | None = None
    dimension: str | None = None
    unit: str = "mm"
    depends_on: tuple[str, ...] = ()
    source: str | None = None
    allowed_range: tuple[float, float] | None = None
    component_kind: str = "editable"
    status: str = "pending_mapping"

    def validate(self):
        if not self.parameter or self.unit not in {"mm", "m", "deg", "count"}:
            raise ValueError("invalid parameter or unit")
        if self.component_kind not in {"editable", "fixed", "purchased"}:
            raise ValueError("invalid component kind")
        if self.status not in {"confirmed", "pending_mapping", "unconfirmed"}:
            raise ValueError("invalid confirmation status")
        if self.allowed_range is not None:
            lo, hi = self.allowed_range
            if not all(isinstance(x, (float, int)) and not isinstance(x, bool) and isfinite(x) for x in (lo, hi)) or lo > hi:
                raise ValueError("invalid allowed range")
        if self.status == "confirmed" and not all((self.document, self.configuration, self.feature, self.dimension, self.source, self.allowed_range is not None)):
            raise ValueError("confirmed mapping requires document/configuration/feature/dimension/source/range")

    @property
    def target(self):
        return (self.document, self.configuration, self.feature, self.dimension)


def load_mappings(payload: dict) -> list[ParameterMapping]:
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported mapping schema_version")
    rows = [ParameterMapping(**row) for row in payload["parameters"]]
    seen, targets = set(), set()
    for row in rows:
        row.validate()
        if row.parameter in seen:
            raise ValueError("duplicate mapping parameter")
        seen.add(row.parameter)
        if row.status == "confirmed":
            if row.target in targets:
                raise ValueError("duplicate physical target")
            targets.add(row.target)
    return rows


def mapping_template(plan: dict) -> dict:
    return {"schema_version": 1, "parameters": [asdict(ParameterMapping(
        parameter=name, unit=row.get("unit", "mm"),
        depends_on=tuple(row.get("depends_on", [])),
        component_kind="fixed" if row.get("preserve_interface") else "editable",
    )) for name, row in plan["parameter_register"].items()]}
