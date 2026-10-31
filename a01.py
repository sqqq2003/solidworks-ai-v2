"""Local A01 coordination and parameter preflight. Never imports legacy or CAD."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
TERMINAL = {"passed", "degraded", "failed", "review_required"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def positive(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected a finite positive number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field}: expected a finite positive number")
    return float(value)


def topological_order(nodes: dict) -> list[str]:
    ordered, visiting, done = [], set(), set()

    def visit(name):
        if name not in nodes:
            raise ValueError(f"Unknown dependency: {name}")
        if name in visiting:
            raise ValueError(f"Dependency cycle: {name}")
        if name in done:
            return
        visiting.add(name)
        for dep in nodes[name].get("depends_on", []):
            visit(dep)
        visiting.remove(name)
        done.add(name)
        ordered.append(name)

    for name in nodes:
        visit(name)
    return ordered


def make_plan(spec: dict) -> dict:
    if spec.get("units") != "mm":
        raise ValueError("Input units must be mm")
    target = spec["target_envelope_mm"]
    target = {axis: positive(target[axis], axis) for axis in ("length", "width", "height")}
    nodes = spec["parameter_graph"]
    order = topological_order(nodes)
    values, unresolved, checks = {}, [], []
    approved = spec.get("engineering_approved") is True
    for name in order:
        node = nodes[name]
        kind = node.get("kind")
        if kind == "input":
            axis = node["axis"]
            values[name] = target[axis]
        elif kind == "measured":
            value = node.get("value_mm")
            if value is None or node.get("confirmed") is not True or not node.get("source"):
                values[name] = None
                unresolved.append({"parameter": name, "reason": "Requires confirmed drawing value and source"})
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{name}: invalid measured dimension")
                values[name] = float(value)
        elif kind == "subtract":
            deps = node.get("depends_on", [])
            if len(deps) < 2:
                raise ValueError(f"{name}: subtract needs a base and at least one offset")
            if any(values[dep] is None for dep in deps):
                values[name] = None
                unresolved.append({"parameter": name, "reason": "Upstream dimensions unresolved"})
            else:
                values[name] = positive(values[deps[0]] - sum(values[dep] for dep in deps[1:]), name)
        else:
            raise ValueError(f"{name}: unsupported parameter rule {kind}")
        limit = node.get("confirmed_range_mm")
        if limit is not None and values[name] is not None:
            if not isinstance(limit, list) or len(limit) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in limit) or limit[0] > limit[1]:
                raise ValueError(f"{name}: invalid confirmed range")
            if not limit[0] <= values[name] <= limit[1]:
                raise ValueError(f"{name}: outside confirmed range")
            checks.append({"parameter": name, "range_mm": limit, "passed": True})
    if not approved:
        unresolved.append({"parameter": "engineering_approval", "reason": "A01 template and valid operating ranges require engineering confirmation"})
    if spec.get("template_identity_confirmed") is not True:
        unresolved.append({"parameter": "template_identity", "reason": "A01 assembly identity is not verified"})
    if not spec.get("native_template"):
        unresolved.append({"parameter": "native_template", "reason": "No verified SolidWorks assembly template"})
    return {
        "machine_id": spec["machine_id"], "spec_revision": spec["revision"],
        "status": "review_required" if unresolved else "passed",
        "scope": "parameter_preflight_only", "cad_executed": False,
        "cad_release_approved": False,
        "target_envelope_mm": target, "parameter_order": order,
        "values_mm": values, "unresolved": unresolved, "range_checks": checks,
        "parameter_register": {name: {"unit": "mm", "depends_on": node.get("depends_on", []),
            "source": node.get("source", "user_target" if node.get("kind") == "input" else None),
            "confirmed_range_mm": node.get("confirmed_range_mm"),
            "confirmation_status": "confirmed_input" if node.get("confirmed") is True else "unconfirmed",
            "production_approved": False} for name, node in nodes.items()},
        "preserve_interfaces": spec.get("preserve_interfaces", []),
        "note": "A passed parameter preflight does not certify geometry, mates or motion.",
    }


def queue_snapshot(board: dict) -> dict:
    tasks = board["tasks"]
    mapping = {t["task_id"]: t for t in tasks}
    if len(mapping) != len(tasks):
        raise ValueError("Duplicate task IDs")
    topological_order(mapping)
    rows = []
    for task in tasks:
        status = task["status"]
        if status not in {"queued", "running"} | TERMINAL:
            raise ValueError(f"Invalid task status: {status}")
        blockers = [dep for dep in task.get("depends_on", []) if mapping[dep]["status"] != "passed"]
        rows.append({**task, "blocked_by": blockers,
                     "ready": status == "queued" and not blockers,
                     "dispatched": task.get("dispatched", False)})
    return {"deployment": "local_development_workspace", "tasks": rows,
            "cad_writer_limit": 1, "external_agents_started": False}


def doctor() -> dict:
    dependencies = {}
    for package in ("ezdxf", "pywin32"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    return {"python": sys.version, "executable": sys.executable,
            "dependencies": dependencies, "cad_connected": "not_probed",
            "mode": "offline", "legacy_imported": False,
            "external_agent_access": {"status": "not_configured", "external_agents_started": False}}


def verify_baseline() -> dict:
    baseline = read_json(ROOT / "baseline.json")
    if not (ROOT / "legacy").is_dir():
        return {"status": "unavailable", "scope": "copied_baseline_integrity",
                "files_checked": 0, "reason": "Original CAD/source archive is intentionally absent from cloud"}
    changes = []
    for row in baseline["files"]:
        path = ROOT / "legacy" / row["path"]
        if not path.is_file() or digest(path) != row["sha256"]:
            changes.append(row["path"])
    return {"status": "passed" if not changes else "failed",
            "scope": "copied_baseline_integrity", "files_checked": len(baseline["files"]),
            "changed": changes}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="A01 本机开发工作台：状态、环境、参数预检；不连接 CAD")
    parser.add_argument("command", choices=("status", "doctor", "plan", "verify-baseline"))
    parser.add_argument("--spec", type=Path, default=ROOT / "data" / "machine_spec.json")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            report = queue_snapshot(read_json(ROOT / "data" / "tasks.json"))
        elif args.command == "doctor":
            report = doctor()
        elif args.command == "plan":
            report = make_plan(read_json(args.spec))
        else:
            report = verify_baseline()
        payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(payload + "\n", encoding="utf-8")
        print(payload)
        if report.get("status") == "review_required":
            return 3
        return 1 if report.get("status") in {"failed", "unavailable"} else 0
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
