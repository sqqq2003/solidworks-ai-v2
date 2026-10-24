"""Whole-machine parameter dependency, assembly-relation and conflict
precheck engine (dependency-engine/1).

Offline, pure Python standard library. This module never talks to
SolidWorks, never writes CAD files, and never reads customer CAD: it
statically checks one machine's parameters and assembly relations and
reports what passes, what conflicts, and what is still unconfirmed.

Design notes (what this reuses, and where it deliberately differs from
its neighbours):

* a01_parametric/graph.py (dev, src/a01_parametric): parameters linked
  by ``depends_on`` edges, kinds ``copy`` / ``pending_mapping``,
  subsystems frame / conveyor / drive / mount, subtract chains, and
  unmapped dimensions staying empty. This engine mirrors that vocabulary:
  formula ops include ``copy``, a parameter with neither value nor
  formula is ``pending_mapping``, and ``subsystem`` is an optional label
  (frame / conveyor / drive / mount / sealing / interfaces / purchased,
  following ql5050px/parameters.py MODULES).
* ql5050px/parameters.py (dev): absent OEM data stays null, only
  confirmed inputs resolve, derived values come from explicit design
  relationships (e.g. frame_length = target_length - 2*end_allowance).
  Same discipline here: a derived parameter resolves only when every
  argument resolves; anything else is pending, never fabricated.
* a01_parametric/constraints.py (dev): units must be explicit, values
  must be positive where the unit is mm, confirmed ranges are enforced,
  and a ``pending_mapping`` parameter must never carry a fabricated
  value. This engine keeps units explicit and turns range violations
  into pending items (see below) instead of inventing a value.
* Module 4 (feature_tree/, Draft PR #36): Kahn topological order
  (input-order stable), dependency cycles rejected, units explicit mm,
  missing per-job values are pending_confirmation. This engine uses the
  same Kahn order and the same cycle discipline.
* Where module 5 differs from module 4 on purpose: module 4 refuses to
  run a tree with a missing dependency, because executing a guessed
  order would build a wrong part. Module 5 is a *precheck* engine: its
  whole job is to report gaps, so a missing value, an unknown formula
  reference, or an out-of-range value makes the affected parameters
  pending (with the gap listed) instead of aborting the report. Only
  structural defects abort the run as input errors: duplicate parameter
  names, dependency cycles, a parameter carrying both a value and a
  formula, an unknown formula op, or a non-explicit unit. Those mean the
  input itself is unusable, not merely unconfirmed.
* Module 3 (dxf_extract/, Draft PR #35): same I/O conventions --
  versioned JSON format string, units explicitly "mm", statuses
  "confirmed" / "pending_confirmation", exit codes 0 = ok / 1 = report
  written but pending or conflicting / 2 = input error, input file never
  modified, outputs only under --out-dir. Feature plans from module 3
  and trees from module 4 are referenced, not rebuilt: a part may list
  ``feature_refs`` (module 3 feature ids / module 4 node ids) so the
  impact scope names the affected features; this engine does not parse
  plan.json or tree JSON itself.
* Sheet-metal parameters (thickness, radius, angle, K factor) are
  ordinary parameters here: they must be supplied per job, exactly as
  csharp-bridge/SHEET_METAL_RULES.md requires. This engine does NOT
  compute bend allowance / deduction -- that formula chain lives in
  modules 2 and 4 and is not duplicated here. There is no default
  thickness, radius, angle or K factor anywhere in this module, and it
  does not reference the leftover generator constant (see README).
"""

from __future__ import annotations

import math

FORMAT_VERSION = "dependency-engine/1"
REPORT_VERSION = "dependency-precheck/1"

ALLOWED_UNITS = frozenset(["mm", "deg", "count", "unitless"])
# Subsystem labels borrowed from a01_parametric (frame/conveyor/drive/
# mount) plus ql5050px MODULES (sealing/interfaces/purchased). Any other
# non-empty string is accepted as a label; it is documentation, not a
# rule, so an unknown subsystem never blocks a precheck.
KNOWN_SUBSYSTEMS = frozenset(
    ["frame", "conveyor", "drive", "mount", "sealing", "interfaces", "purchased"]
)

# Mate kinds. Position-fixing kinds carry an implied numeric value on
# the axis they fix, measured from part_a to part_b: coincident and
# align both mean "same position on that axis" (value 0); distance
# means the given separation. parallel / perpendicular fix orientation
# only and never participate in position-conflict checks.
POSITION_MATE_KINDS = frozenset(["coincident", "distance", "align"])
ORIENTATION_MATE_KINDS = frozenset(["parallel", "perpendicular"])
MATE_KINDS = POSITION_MATE_KINDS | ORIENTATION_MATE_KINDS

_EPS = 1e-9


class InputError(ValueError):
    """The input document itself is unusable (not merely unconfirmed)."""


class CycleError(InputError):
    """Parameter dependency graph contains a cycle; no order is guessed."""


class DuplicateNameError(InputError):
    """Two parameters share one name."""


def _is_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


class Parameter:
    """One machine parameter: a leaf value, a formula, or pending."""

    def __init__(self, raw: dict):
        if not isinstance(raw, dict):
            raise InputError("parameter must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise InputError("parameter needs a non-empty string name")
        self.name = name
        unit = raw.get("unit")
        if unit not in ALLOWED_UNITS:
            raise InputError(
                "%s: unit must be one of %s, got %r (units are explicit, never assumed)"
                % (name, sorted(ALLOWED_UNITS), unit)
            )
        self.unit = unit
        self.subsystem = raw.get("subsystem")
        if self.subsystem is not None and not isinstance(self.subsystem, str):
            raise InputError("%s: subsystem must be a string" % name)
        self.minimum = raw.get("min")
        self.maximum = raw.get("max")
        for label, bound in (("min", self.minimum), ("max", self.maximum)):
            if bound is not None and not _is_number(bound):
                raise InputError("%s: %s must be a number" % (name, label))
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise InputError("%s: min must not exceed max" % name)
        has_value = "value" in raw and raw["value"] is not None
        has_formula = "formula" in raw and raw["formula"] is not None
        if has_value and has_formula:
            raise InputError(
                "%s: carries both a value and a formula; ambiguous input is refused"
                % name
            )
        self.value = None
        if has_value:
            if not _is_number(raw["value"]):
                raise InputError("%s: value must be a finite number" % name)
            self.value = float(raw["value"])
        self.formula = None
        if has_formula:
            formula = raw["formula"]
            if not isinstance(formula, dict):
                raise InputError("%s: formula must be an object" % name)
            op = formula.get("op")
            if op not in ("copy", "add", "subtract", "scale"):
                raise InputError("%s: unknown formula op %r" % (name, op))
            if op == "scale":
                args = formula.get("args")
                if not isinstance(args, list) or len(args) != 1:
                    raise InputError("%s: scale needs exactly one arg" % name)
                if not _is_number(formula.get("factor")):
                    raise InputError("%s: scale needs a numeric factor" % name)
            else:
                args = formula.get("args")
                if not isinstance(args, list) or not args:
                    raise InputError("%s: formula needs a non-empty args list" % name)
            if not all(isinstance(a, str) for a in args):
                raise InputError("%s: formula args must be parameter names" % name)
            self.formula = {
                "op": op,
                "args": list(args),
                "factor": formula.get("factor"),
            }
        # Resolution outcome, filled in by resolve().
        self.status = "pending_confirmation"
        self.resolved = None
        self.pending_reasons = []
        if self.formula is None and self.value is None:
            self.pending_reasons = ["pending_mapping"]

    def formula_args(self) -> list:
        return list(self.formula["args"]) if self.formula else []

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "unit": self.unit,
            "status": self.status,
            "value": self.resolved,
            "pending_reasons": list(self.pending_reasons),
        }
        if self.subsystem is not None:
            data["subsystem"] = self.subsystem
        if self.formula is not None:
            data["formula"] = dict(self.formula)
        return data


class Mate:
    """One assembly constraint between two parts."""

    def __init__(self, raw: dict):
        if not isinstance(raw, dict):
            raise InputError("mate must be an object")
        mate_id = raw.get("id")
        if not isinstance(mate_id, str) or not mate_id:
            raise InputError("mate needs a non-empty string id")
        self.id = mate_id
        kind = raw.get("kind")
        if kind not in MATE_KINDS:
            raise InputError("%s: unknown mate kind %r" % (mate_id, kind))
        self.kind = kind
        for key in ("part_a", "part_b"):
            if not isinstance(raw.get(key), str) or not raw[key]:
                raise InputError("%s: %s must be a non-empty string" % (mate_id, key))
        self.part_a = raw["part_a"]
        self.part_b = raw["part_b"]
        self.axis = raw.get("axis")
        if kind in ("distance", "align"):
            if self.axis not in ("x", "y", "z"):
                raise InputError(
                    "%s: %s mate needs axis x, y or z" % (mate_id, kind)
                )
        self.value_mm = raw.get("value_mm")
        self.value_param = raw.get("value_param")
        if kind == "distance":
            if self.value_mm is not None and self.value_param is not None:
                raise InputError(
                    "%s: distance mate carries both value_mm and value_param" % mate_id
                )
            if self.value_mm is not None and not _is_number(self.value_mm):
                raise InputError("%s: value_mm must be a number" % mate_id)
            if self.value_param is not None and not isinstance(self.value_param, str):
                raise InputError("%s: value_param must be a parameter name" % mate_id)
        self.status = "confirmed"
        self.pending_reasons = []

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "part_a": self.part_a,
            "part_b": self.part_b,
            "status": self.status,
            "pending_reasons": list(self.pending_reasons),
        }
        if self.axis is not None:
            data["axis"] = self.axis
        if self.value_mm is not None:
            data["value_mm"] = self.value_mm
        if self.value_param is not None:
            data["value_param"] = self.value_param
        return data


def parse_machine(data: dict) -> dict:
    """Validate a dependency-engine/1 document (structural checks only).

    Returns a dict of {name, units, parameters, parts, mates}. Raises
    InputError on duplicate names, cycles, ambiguous values, unknown
    ops/kinds, or non-explicit units. Missing values and unknown formula
    references are NOT errors here -- they become pending items during
    resolution, because reporting gaps is this engine's job.
    """
    if not isinstance(data, dict):
        raise InputError("machine document must be an object")
    if data.get("format") != FORMAT_VERSION:
        raise InputError(
            "unsupported format: %r (expected %r)" % (data.get("format"), FORMAT_VERSION)
        )
    if data.get("units") != "mm":
        raise InputError("units must be explicitly 'mm', got %r" % data.get("units"))
    raw_params = data.get("parameters")
    if not isinstance(raw_params, list) or not raw_params:
        raise InputError("machine needs a non-empty 'parameters' list")
    params = {}
    order = []
    for raw in raw_params:
        param = Parameter(raw)
        if param.name in params:
            raise DuplicateNameError("duplicate parameter name: %s" % param.name)
        params[param.name] = param
        order.append(param.name)
    raw_parts = data.get("parts", [])
    if not isinstance(raw_parts, list):
        raise InputError("'parts' must be a list")
    parts = {}
    for raw in raw_parts:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            raise InputError("part needs a non-empty string id")
        if raw["id"] in parts:
            raise InputError("duplicate part id: %s" % raw["id"])
        uses = raw.get("uses_parameters", [])
        if not isinstance(uses, list) or not all(isinstance(u, str) for u in uses):
            raise InputError("part %s: uses_parameters must be a list of names" % raw["id"])
        refs = raw.get("feature_refs", [])
        if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
            raise InputError("part %s: feature_refs must be a list of ids" % raw["id"])
        parts[raw["id"]] = {
            "id": raw["id"],
            "label": raw.get("label", ""),
            "uses_parameters": list(uses),
            "feature_refs": list(refs),
        }
    raw_mates = data.get("mates", [])
    if not isinstance(raw_mates, list):
        raise InputError("'mates' must be a list")
    mates = [Mate(raw) for raw in raw_mates]
    mate_ids = set()
    for mate in mates:
        if mate.id in mate_ids:
            raise InputError("duplicate mate id: %s" % mate.id)
        mate_ids.add(mate.id)
    # Cycle check now, so a cyclic graph can never reach resolution.
    resolution_order(params)
    return {
        "name": data.get("name", ""),
        "units": "mm",
        "parameters": params,
        "order": order,
        "parts": parts,
        "mates": mates,
    }


def resolution_order(params: dict) -> list:
    """Topological order of parameter names (Kahn, input-order stable).

    Raises CycleError listing the unplaced names when the graph has a
    cycle. Unknown formula references are ignored here -- they become
    pending items during resolution, not ordering failures.
    """
    indegree = {name: 0 for name in params}
    followers: dict[str, list] = {name: [] for name in params}
    for name, param in params.items():
        for dep in param.formula_args():
            if dep in params and dep != name:
                followers[dep].append(name)
                indegree[name] += 1
    ready = [name for name in params if indegree[name] == 0]
    ordered = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for nxt in followers[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if len(ordered) != len(params):
        remaining = sorted(n for n in params if n not in ordered)
        raise CycleError(
            "parameter dependency cycle involving: %s" % ", ".join(remaining)
        )
    return ordered


def _apply_formula(formula: dict, values: dict):
    op = formula["op"]
    args = [values[a] for a in formula["args"]]
    if op == "copy":
        return args[0]
    if op == "add":
        return sum(args)
    if op == "subtract":
        result = args[0]
        for other in args[1:]:
            result -= other
        return result
    if op == "scale":
        return args[0] * float(formula["factor"])
    raise InputError("unknown formula op %r" % op)


def resolve(machine: dict) -> None:
    """Resolve every parameter in topological order, in place.

    A parameter resolves only when all of its inputs resolve. Otherwise
    it is pending_confirmation with reasons naming the gap: a missing
    leaf value (pending_mapping), an unknown formula reference, a
    pending upstream parameter, a range violation, or a division-style
    failure (non-finite result). Nothing is ever filled with a guessed
    number.
    """
    params = machine["parameters"]
    for name in resolution_order(params):
        param = params[name]
        if param.formula is None:
            if param.value is None:
                param.status = "pending_confirmation"
                param.resolved = None
                if "pending_mapping" not in param.pending_reasons:
                    param.pending_reasons = ["pending_mapping"]
            else:
                param.resolved = param.value
                param.status = "confirmed"
                param.pending_reasons = []
                _check_range(param)
            continue
        missing = []
        for dep in param.formula_args():
            if dep not in params:
                missing.append("unknown_reference:%s" % dep)
            elif params[dep].status != "confirmed":
                missing.append(dep)
        if missing:
            param.status = "pending_confirmation"
            param.resolved = None
            param.pending_reasons = ["unresolved_dependency:%s" % ",".join(missing)]
            continue
        values = {dep: params[dep].resolved for dep in param.formula_args()}
        try:
            result = _apply_formula(param.formula, values)
        except (ArithmeticError, ValueError, OverflowError):
            param.status = "pending_confirmation"
            param.resolved = None
            param.pending_reasons = ["formula_evaluation_failed"]
            continue
        if not _is_number(result):
            param.status = "pending_confirmation"
            param.resolved = None
            param.pending_reasons = ["formula_result_not_finite"]
            continue
        param.resolved = float(result)
        param.status = "confirmed"
        param.pending_reasons = []
        _check_range(param)


def _check_range(param: Parameter) -> None:
    """Turn a range violation into pending (never clamp, never guess)."""
    if param.resolved is None:
        return
    if param.minimum is not None and param.resolved < param.minimum - _EPS:
        param.status = "pending_confirmation"
        param.pending_reasons = [
            "out_of_range:below_min:%s" % _fmt(param.minimum)
        ]
    elif param.maximum is not None and param.resolved > param.maximum + _EPS:
        param.status = "pending_confirmation"
        param.pending_reasons = [
            "out_of_range:above_max:%s" % _fmt(param.maximum)
        ]


def _fmt(value: float) -> str:
    if float(value) == int(float(value)):
        return str(int(float(value)))
    return repr(float(value))


def _mate_position_value(mate: Mate, machine: dict):
    """Numeric position value a mate implies on its axis, or None.

    coincident / align imply 0 (same position). distance uses its
    literal value or its resolved parameter. Returns (value, pending)
    where pending is a reason string when the value cannot be known.
    """
    if mate.kind in ("coincident", "align"):
        return 0.0, None
    if mate.kind == "distance":
        if mate.value_mm is not None:
            return float(mate.value_mm), None
        if mate.value_param is not None:
            param = machine["parameters"].get(mate.value_param)
            if param is None:
                return None, "unknown_reference:%s" % mate.value_param
            if param.status != "confirmed":
                return None, "unresolved_dependency:%s" % mate.value_param
            return float(param.resolved), None
        return None, "missing_distance_value"
    return None, None


def check_mates(machine: dict) -> list:
    """Pair-level assembly conflict detection (static, no CAD solving).

    Rules, all checked per (part_a, part_b, axis) pair so that normal
    assemblies located by several mates to *different* counterparts are
    not falsely flagged:
    * self-mate -> error.
    * unknown part reference -> the mate is pending.
    * distance value unresolvable -> the mate is pending.
    * two position mates on the same pair+axis with different values ->
      error (contradiction).
    * two position mates on the same pair+axis with equal values ->
      warning (redundant constraint).
    * a part with no position mate at all -> warning (under_constrained).
    Orientation mates (parallel / perpendicular) never fix a position
    axis and never participate in these checks. This is a static
    precheck, not a full degree-of-freedom solver: it does not prove a
    whole assembly is fully constrained, and it does not move geometry.
    """
    params = machine["parameters"]
    parts = machine["parts"]
    conflicts = []
    # First pass: mate-level status.
    for mate in machine["mates"]:
        if mate.part_a == mate.part_b:
            mate.status = "conflict"
            mate.pending_reasons = ["self_mate"]
            conflicts.append(
                {
                    "severity": "error",
                    "kind": "self_mate",
                    "mates": [mate.id],
                    "parts": [mate.part_a],
                    "message": "mate %s constrains part %s to itself"
                    % (mate.id, mate.part_a),
                }
            )
            continue
        unknown = [p for p in (mate.part_a, mate.part_b) if p not in parts]
        if unknown:
            mate.status = "pending_confirmation"
            mate.pending_reasons = ["unknown_part:%s" % ",".join(unknown)]
            continue
        if mate.kind == "distance":
            _, pending = _mate_position_value(mate, machine)
            if pending is not None:
                mate.status = "pending_confirmation"
                mate.pending_reasons = [pending]
                continue
        mate.status = "confirmed"
        mate.pending_reasons = []
    # Second pass: pair+axis position conflicts (confirmed mates only).
    # A coincident mate fixes all three axes, so it is expanded into
    # one entry per axis; otherwise it would never be compared against
    # a distance mate on the same pair.
    pair_axes: dict = {}
    for mate in machine["mates"]:
        if mate.status != "confirmed" or mate.kind not in POSITION_MATE_KINDS:
            continue
        value, _ = _mate_position_value(mate, machine)
        axes = ("x", "y", "z") if mate.kind == "coincident" else (mate.axis,)
        for axis in axes:
            key = (frozenset((mate.part_a, mate.part_b)), axis)
            pair_axes.setdefault(key, []).append((mate, value))
    for (pair, axis), rows in sorted(
        pair_axes.items(), key=lambda kv: (sorted(kv[0][0]), kv[0][1])
    ):
        if len(rows) < 2:
            continue
        values = [v for _, v in rows]
        mate_ids = [m.id for m, _ in rows]
        part_list = sorted(pair)
        if all(abs(v - values[0]) <= _EPS for v in values):
            conflicts.append(
                {
                    "severity": "warning",
                    "kind": "redundant_constraint",
                    "mates": mate_ids,
                    "parts": part_list,
                    "message": "mates %s fix the same pair on axis %s with the same "
                    "value %s; one of them is redundant"
                    % (", ".join(mate_ids), axis, _fmt(values[0])),
                }
            )
        else:
            conflicts.append(
                {
                    "severity": "error",
                    "kind": "contradiction",
                    "mates": mate_ids,
                    "parts": part_list,
                    "message": "mates %s disagree on axis %s: values %s"
                    % (
                        ", ".join(mate_ids),
                        axis,
                        ", ".join(_fmt(v) for v in values),
                    ),
                }
            )
    # Third pass: parts with no position mate at all.
    positioned = set()
    for mate in machine["mates"]:
        if mate.status == "confirmed" and mate.kind in POSITION_MATE_KINDS:
            positioned.add(mate.part_a)
            positioned.add(mate.part_b)
    for part_id in sorted(parts):
        if part_id not in positioned:
            conflicts.append(
                {
                    "severity": "warning",
                    "kind": "under_constrained",
                    "mates": [],
                    "parts": [part_id],
                    "message": "part %s has no position mate; its location is "
                    "unconstrained in this model" % part_id,
                }
            )
    return conflicts


def impact_map(machine: dict) -> dict:
    """Transitive impact of changing each parameter.

    impact[name] = {parameters, parts, mates, feature_refs}: every
    downstream parameter (in resolution order), every part using any of
    them, every mate whose distance value comes from any of them, and
    every feature reference carried by those parts (module 3 feature
    ids / module 4 node ids, listed for the caller, not interpreted).
    """
    params = machine["parameters"]
    order = resolution_order(params)
    followers: dict[str, list] = {name: [] for name in params}
    for name, param in params.items():
        for dep in param.formula_args():
            if dep in params:
                followers[dep].append(name)
    result = {}
    for name in params:
        seen = set()
        stack = list(followers[name])
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(followers[current])
        downstream = [n for n in order if n in seen]
        affected = {name} | seen
        parts = sorted(
            pid
            for pid, part in machine["parts"].items()
            if affected & set(part["uses_parameters"])
        )
        mates = sorted(
            mate.id
            for mate in machine["mates"]
            if mate.value_param in affected
        )
        feature_refs = sorted(
            {
                ref
                for pid in parts
                for ref in machine["parts"][pid]["feature_refs"]
            }
        )
        result[name] = {
            "parameters": downstream,
            "parts": parts,
            "mates": mates,
            "feature_refs": feature_refs,
        }
    return result


def confirm_chains(machine: dict, impacts: dict) -> list:
    """'Before changing X, confirm Y' chains for every parameter.

    confirm_first lists the transitive upstream parameters of X that are
    still pending (plus any unknown formula references): changing X
    before those are confirmed risks building on unconfirmed numbers.
    affected repeats the impact scope so the caller sees the blast
    radius in the same row.
    """
    params = machine["parameters"]
    chains = []
    for name in machine["order"]:
        upstream = set()
        stack = list(params[name].formula_args())
        while stack:
            current = stack.pop()
            if current in upstream:
                continue
            upstream.add(current)
            if current in params:
                stack.extend(params[current].formula_args())
        confirm_first = sorted(
            u
            for u in upstream
            if u not in params or params[u].status != "confirmed"
        )
        chains.append(
            {
                "change": name,
                "confirm_first": confirm_first,
                "affected": impacts[name],
            }
        )
    return chains


def precheck(data: dict) -> dict:
    """Run the full static precheck and return the report document."""
    machine = parse_machine(data)
    resolve(machine)
    conflicts = check_mates(machine)
    impacts = impact_map(machine)
    chains = confirm_chains(machine, impacts)
    pending_items = []
    for name in machine["order"]:
        param = machine["parameters"][name]
        if param.status != "confirmed":
            pending_items.append(
                {
                    "kind": "parameter",
                    "name": name,
                    "reasons": list(param.pending_reasons),
                }
            )
    for mate in machine["mates"]:
        if mate.status == "pending_confirmation":
            pending_items.append(
                {
                    "kind": "mate",
                    "name": mate.id,
                    "reasons": list(mate.pending_reasons),
                }
            )
    has_error = any(c["severity"] == "error" for c in conflicts)
    status = "conflict" if has_error else ("pending" if pending_items else "ok")
    return {
        "format": REPORT_VERSION,
        "name": machine["name"],
        "units": "mm",
        "status": status,
        "parameters": [machine["parameters"][n].to_dict() for n in machine["order"]],
        "resolution_order": resolution_order(machine["parameters"]),
        "parts": [
            {
                "id": part["id"],
                "label": part["label"],
                "uses_parameters": list(part["uses_parameters"]),
                "feature_refs": list(part["feature_refs"]),
            }
            for part in machine["parts"].values()
        ],
        "mates": [mate.to_dict() for mate in machine["mates"]],
        "conflicts": conflicts,
        "pending_items": pending_items,
        "impact": impacts,
        "confirm_chains": chains,
    }
