"""Machine registry: one entry per machine, each with its own spec and planner.

The registry is a structural index only. It never invents OEM-confirmed
dimensions: a machine's real values live in its spec's confirmed mapping
nodes (pending until an engineering approval exists). Adding a machine means
adding a spec file plus one entry here; no parallel planner codebases.
"""
from __future__ import annotations

import json
from pathlib import Path

MODULE = "issue6-machine-registry"

_SRC = Path(__file__).resolve().parent
ROOT = _SRC.parent
REGISTRY_PATH = ROOT / "data" / "machines" / "index.json"


class MachineRegistryError(ValueError):
    """Raised when the registry or a machine entry is structurally invalid."""


def load_registry(path: Path | None = None) -> dict:
    path = Path(path) if path is not None else REGISTRY_PATH
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MachineRegistryError(f"machine registry not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MachineRegistryError(f"machine registry is not valid JSON: {exc}") from exc
    _validate_registry(registry)
    return registry


def _validate_registry(registry: dict) -> None:
    if not isinstance(registry, dict):
        raise MachineRegistryError("registry must be a JSON object")
    if registry.get("registry_version") != 1:
        raise MachineRegistryError("unsupported registry_version; expected 1")
    machines = registry.get("machines")
    if not isinstance(machines, list) or not machines:
        raise MachineRegistryError("registry must list at least one machine")
    seen: set[str] = set()
    for entry in machines:
        for field in ("id", "name", "spec", "planner", "status"):
            if not entry.get(field):
                raise MachineRegistryError(f"registry entry missing field: {field}")
        machine_id = entry["id"]
        if machine_id in seen:
            raise MachineRegistryError(f"duplicate machine id: {machine_id}")
        seen.add(machine_id)
        if not (ROOT / entry["spec"]).is_file():
            raise MachineRegistryError(f"spec file missing for {machine_id}: {entry['spec']}")


def list_machines(path: Path | None = None) -> list[dict]:
    """Return summary rows: id, name, family, status. No dimension values."""
    registry = load_registry(path)
    return [
        {
            "id": entry["id"],
            "machine_id": entry.get("machine_id"),
            "name": entry["name"],
            "family": entry.get("family"),
            "status": entry["status"],
        }
        for entry in registry["machines"]
    ]


def get_machine(machine_id: str, path: Path | None = None) -> dict:
    registry = load_registry(path)
    for entry in registry["machines"]:
        if entry["id"] == machine_id:
            return entry
    known = ", ".join(sorted(e["id"] for e in registry["machines"]))
    raise MachineRegistryError(f"unknown machine id: {machine_id} (known: {known})")


def resolve_spec_path(machine_id: str, path: Path | None = None) -> Path:
    entry = get_machine(machine_id, path)
    spec = ROOT / entry["spec"]
    if not spec.is_file():
        raise MachineRegistryError(f"spec file missing for {machine_id}: {spec}")
    return spec


def load_machine_spec(machine_id: str, path: Path | None = None) -> dict:
    return json.loads(resolve_spec_path(machine_id, path).read_text(encoding="utf-8"))
