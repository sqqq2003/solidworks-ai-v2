"""BOM builder + CSV / table renderers (phase 1, F3).

Input document (bom/1, plain JSON):

    {
      "assembly_name": "...",
      "parts": [
        {"id": "beam_front", "name": "前横梁", "material": "Q235",
         "quantity": 2, "mass_kg": 4.5,
         "depends_on": ["column_left"]}
      ]
    }

``mass_kg`` is optional per part; ``depends_on`` is optional per
part. Everything else is required and explicit. Output document
(bom/1): rows in assembly order, per-row pending notes, total mass
only when every row's mass is known, and a dependency cross-check
section when a precheck report is supplied.
"""

from __future__ import annotations

import csv
import io

BOM_VERSION = "bom/1"


class BomError(ValueError):
    """Malformed input (wrong shape, duplicate id, dependency cycle)."""


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_part(part: dict) -> None:
    if not isinstance(part, dict):
        raise BomError("each part must be an object")
    if not isinstance(part.get("id"), str) or not part["id"]:
        raise BomError("each part needs a non-empty string id")
    for field in ("name", "material"):
        if not isinstance(part.get(field), str) or not part[field]:
            raise BomError(
                "part %s needs a non-empty string %s"
                % (part["id"], field)
            )
    quantity = part.get("quantity")
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
    ):
        raise BomError(
            "part %s quantity must be an integer > 0" % part["id"]
        )
    if "mass_kg" in part:
        mass = part["mass_kg"]
        if not _is_number(mass) or mass < 0:
            raise BomError(
                "part %s mass_kg must be a number >= 0" % part["id"]
            )
    depends = part.get("depends_on", [])
    if not isinstance(depends, list) or any(
        not isinstance(d, str) for d in depends
    ):
        raise BomError(
            "part %s depends_on must be a list of strings" % part["id"]
        )


def _assembly_order(parts: list) -> tuple:
    """Topological order by depends_on, or (None, cycle) on a cycle.

    Edges to ids outside the BOM are not ordering edges; they are
    reported as unresolved dependencies by the caller.
    """
    ids = {p["id"] for p in parts}
    remaining = {p["id"]: p for p in parts}
    order = []
    while remaining:
        ready = [
            pid
            for pid, part in remaining.items()
            if all(
                dep not in remaining for dep in part.get("depends_on", [])
            )
        ]
        if not ready:
            return None, sorted(remaining)
        for pid in sorted(ready):
            order.append(remaining.pop(pid))
    return order, None


def build_bom(assembly: dict, dependency_report: dict | None = None) -> dict:
    """Build the BOM document (or raise BomError on malformed input)."""
    if not isinstance(assembly, dict):
        raise BomError("assembly must be a JSON object")
    name = assembly.get("assembly_name")
    if not isinstance(name, str) or not name:
        raise BomError("assembly_name must be a non-empty string")
    parts = assembly.get("parts")
    if not isinstance(parts, list) or not parts:
        raise BomError("parts must be a non-empty list")
    seen = set()
    for part in parts:
        _validate_part(part)
        if part["id"] in seen:
            raise BomError("duplicate part id: %s" % part["id"])
        seen.add(part["id"])
    order, cycle = _assembly_order(parts)
    if cycle is not None:
        raise BomError(
            "dependency cycle among parts: %s" % ", ".join(cycle)
        )
    ids = {p["id"] for p in parts}
    dep_check = {"checked": False, "unmatched_ids": [], "name_match": None}
    if dependency_report is not None:
        if not isinstance(dependency_report, dict):
            raise BomError("dependency_report must be a JSON object")
        dep_check["checked"] = True
        report_ids = {
            p.get("id")
            for p in dependency_report.get("parts", [])
            if isinstance(p, dict)
        }
        dep_check["unmatched_ids"] = sorted(ids - report_ids)
        report_name = dependency_report.get("name")
        dep_check["name_match"] = report_name == name
    rows = []
    pending = []
    total_mass = 0.0
    all_masses_known = True
    for line_no, part in enumerate(order, start=1):
        row_pending = []
        for dep in part.get("depends_on", []):
            if dep not in ids:
                row_pending.append("unresolved_dependency:%s" % dep)
        if dep_check["checked"] and part["id"] in dep_check["unmatched_ids"]:
            row_pending.append("not_in_dependency_graph")
        mass = part.get("mass_kg")
        if mass is None:
            all_masses_known = False
            row_pending.append("mass_pending")
            row_mass = None
        else:
            row_mass = mass * part["quantity"]
            total_mass += row_mass
        pending.extend(
            "%s:%s" % (part["id"], reason) for reason in row_pending
        )
        rows.append(
            {
                "line_no": line_no,
                "id": part["id"],
                "name": part["name"],
                "material": part["material"],
                "quantity": part["quantity"],
                "mass_kg": mass,
                "total_mass_kg": row_mass,
                "pending_reasons": row_pending,
            }
        )
    if dep_check["checked"] and dep_check["name_match"] is False:
        pending.append("assembly_name_mismatch")
    return {
        "bom_version": BOM_VERSION,
        "assembly_name": name,
        "status": "pending" if pending else "ok",
        "rows": rows,
        "total_quantity": sum(r["quantity"] for r in rows),
        "total_mass_kg": total_mass if all_masses_known else None,
        "dependency_check": dep_check,
        "pending": pending,
    }


def render_csv(bom_doc: dict) -> str:
    """CSV text (Excel-readable; the CLI writes it as UTF-8-SIG)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["序号", "零件号", "名称", "材质", "数量", "单重kg", "总重kg"]
    )
    for row in bom_doc["rows"]:
        writer.writerow(
            [
                row["line_no"],
                row["id"],
                row["name"],
                row["material"],
                row["quantity"],
                "" if row["mass_kg"] is None else row["mass_kg"],
                "" if row["total_mass_kg"] is None else row["total_mass_kg"],
            ]
        )
    return buffer.getvalue()


def render_table(bom_doc: dict) -> str:
    """Plain-text detail table, pasteable into a drawing's notes."""
    lines = []
    lines.append(
        "BOM: %s (bom/1)" % bom_doc["assembly_name"]
    )
    lines.append(
        "序号 | 零件号 | 名称 | 材质 | 数量 | 单重kg | 总重kg"
    )
    for row in bom_doc["rows"]:
        lines.append(
            "%s | %s | %s | %s | %s | %s | %s"
            % (
                row["line_no"],
                row["id"],
                row["name"],
                row["material"],
                row["quantity"],
                "" if row["mass_kg"] is None else row["mass_kg"],
                (
                    ""
                    if row["total_mass_kg"] is None
                    else row["total_mass_kg"]
                ),
            )
        )
    total = bom_doc["total_mass_kg"]
    lines.append(
        "合计数量: %s  合计重量kg: %s"
        % (
            bom_doc["total_quantity"],
            "待确认" if total is None else total,
        )
    )
    return "\n".join(lines) + "\n"
