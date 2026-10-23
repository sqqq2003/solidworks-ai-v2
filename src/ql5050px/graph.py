"""Dependency edges for the independent QL-5050PX graph.

Frame edges live in ``parameter_graph`` and are evaluated by ``a01.make_plan``.
Later edges live in ``parametric_graph``: a ``copy`` edge repeats an already
resolved dimension (generic rule, not an OEM measurement); a
``pending_mapping`` edge keeps the real-model dimension empty.

Subsystems
----------
frame (机架)
    Target envelope placeholder and measured allowances. Frame length, width
    and column height are subtract chains. Unconfirmed allowances leave those
    results empty.
conveyor (输送面)
    Depends on the frame. Bed length and clear width copy the frame when it
    resolves. Passline height stays unmapped.
carton (纸箱通道)
    Depends on the frame. Passage dimensions stay unmapped.
drive (传动)
    Depends on the conveyor bed. Drive center stays unmapped. Chain pitch and
    tooth count are preserved interfaces.
mount (安装位置)
    Depends on the frame. Motor and bearing positions stay unmapped. Sheet
    thickness and thread diameter are preserved interfaces.
"""

from __future__ import annotations

FRAME_NODES = (
    "length",
    "width",
    "height",
    "front_allowance",
    "rear_allowance",
    "left_allowance",
    "right_allowance",
    "top_allowance",
    "bottom_allowance",
    "frame_length",
    "frame_width",
    "column_height",
)

SUBSYSTEMS = ("frame", "conveyor", "carton", "drive", "mount")

# upstream, downstream, subsystem, kind
DOCUMENTED_EXTRA_EDGES = (
    ("frame_length", "conveyor_bed_length", "conveyor", "copy"),
    ("frame_width", "conveyor_clear_width", "conveyor", "copy"),
    ("column_height", "passline_height", "conveyor", "pending_mapping"),
    ("frame_length", "carton_passage_length", "carton", "pending_mapping"),
    ("frame_width", "carton_passage_width", "carton", "pending_mapping"),
    ("column_height", "carton_passage_height", "carton", "pending_mapping"),
    ("conveyor_bed_length", "drive_center_along_length", "drive", "pending_mapping"),
    ("drive_center_along_length", "chain_pitch", "drive", "pending_mapping"),
    ("chain_pitch", "sprocket_teeth", "drive", "pending_mapping"),
    ("frame_length", "motor_mount_x", "mount", "pending_mapping"),
    ("column_height", "motor_mount_z", "mount", "pending_mapping"),
    ("frame_width", "bearing_mount_span", "mount", "pending_mapping"),
    ("frame_length", "sheet_thickness", "mount", "pending_mapping"),
    ("sheet_thickness", "thread_major_diameter", "mount", "pending_mapping"),
)


def subsystem_of(name: str, spec: dict) -> str:
    if name in spec.get("parameter_graph", {}):
        if name not in FRAME_NODES:
            raise ValueError(f"{name}: base parameter is not classified in the frame graph")
        return "frame"
    node = spec.get("parametric_graph", {}).get(name)
    if node is None:
        raise ValueError(f"{name}: parameter is not in the QL-5050PX graph")
    subsystem = node.get("subsystem")
    if subsystem not in SUBSYSTEMS:
        raise ValueError(f"{name}: subsystem must be one of {SUBSYSTEMS}")
    return subsystem


def iter_edges(spec: dict) -> list[dict]:
    rows: list[dict] = []
    for name, node in spec["parameter_graph"].items():
        for upstream in node.get("depends_on", []):
            rows.append(
                {
                    "upstream": upstream,
                    "downstream": name,
                    "subsystem": subsystem_of(name, spec),
                    "kind": node.get("kind"),
                    "meaning": node.get("meaning", ""),
                }
            )
    for name, node in spec.get("parametric_graph", {}).items():
        for upstream in node.get("depends_on", []):
            rows.append(
                {
                    "upstream": upstream,
                    "downstream": name,
                    "subsystem": subsystem_of(name, spec),
                    "kind": node.get("kind"),
                    "meaning": node.get("meaning", ""),
                    "mapping_id": node.get("mapping_id"),
                    "preserve_interface": node.get("preserve_interface"),
                }
            )
    return rows


def assert_documented(spec: dict) -> None:
    """Fail if the spec edges drift away from the documented list."""

    extra = [
        (row["upstream"], row["downstream"], row["subsystem"], row["kind"])
        for row in iter_edges(spec)
        if row["downstream"] not in spec["parameter_graph"]
    ]
    if tuple(extra) != DOCUMENTED_EXTRA_EDGES:
        raise ValueError("parametric_graph edges do not match graph.DOCUMENTED_EXTRA_EDGES")
    for name in spec["parameter_graph"]:
        subsystem_of(name, spec)
