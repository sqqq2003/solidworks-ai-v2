"""Dependency-ordered feature-tree executor (fail-stop).

Semantics (mirrors the #31 wiring discipline and the #23 teardown
discipline, applied to feature execution):

* The tree is validated before anything runs (parse_tree): duplicates,
  unknown types, missing dependencies and cycles refuse execution.
* Nodes run in topological order. The first node that cannot run
  (pending_confirmation status, missing parameter, unsupported type,
  backend failure) STOPS the run: later nodes get no step record and
  no artifact entry, so a failure can never pollute later features.
* The execution record is the evidence: every executed step, the
  failing node (if any), pending reasons, and a mock artifact record
  covering only the nodes that actually executed.
* The executor never writes outside the caller's out-dir (the CLI
  enforces that); it holds no file handles and no COM objects.
"""

from __future__ import annotations

from .mock_backend import StepFailed, StepPending
from .tree import execution_order


class ExecutionRecord:
    """Evidence of one execution run (mock or real-backend stub)."""

    def __init__(self, tree_name: str, backend_name: str):
        self.tree_name = tree_name
        self.backend_name = backend_name
        self.steps: list = []
        self.executed: list = []
        self.status = "ok"
        self.failed_node: str | None = None
        self.failure_kind: str | None = None
        self.failure_detail: str | None = None
        self.pending: list = []

    def to_dict(self) -> dict:
        return {
            "record_version": "feature-tree-execution/1",
            "tree_name": self.tree_name,
            "backend": self.backend_name,
            "evidence_level": "mock",
            "status": self.status,
            "executed": self.executed,
            "steps": self.steps,
            "failed_node": self.failed_node,
            "failure_kind": self.failure_kind,
            "failure_detail": self.failure_detail,
            "pending": self.pending,
        }


class Executor:
    """Runs a validated FeatureTree against a backend.

    backend must expose execute(node) -> step dict, raising StepPending
    or StepFailed (or any exception, which is treated as a failure).
    """

    def __init__(self, backend, backend_name: str = "mock"):
        self.backend = backend
        self.backend_name = backend_name

    def run(self, tree) -> ExecutionRecord:
        record = ExecutionRecord(tree.name, self.backend_name)
        order = execution_order(tree)
        nodes = {node.id: node for node in tree.features}
        for node_id in order:
            node = nodes[node_id]
            if node.status == "pending_confirmation":
                record.status = "failed"
                record.failed_node = node_id
                record.failure_kind = "pending_confirmation"
                record.failure_detail = "; ".join(node.pending_reasons)
                record.pending.append(
                    {"node_id": node_id, "reasons": list(node.pending_reasons)}
                )
                break
            try:
                step = self.backend.execute(node)
            except StepPending as exc:
                record.status = "failed"
                record.failed_node = node_id
                record.failure_kind = "pending_confirmation"
                record.failure_detail = "; ".join(exc.reasons)
                record.pending.append(
                    {"node_id": node_id, "reasons": list(exc.reasons)}
                )
                break
            except StepFailed as exc:
                record.status = "failed"
                record.failed_node = node_id
                record.failure_kind = "failed"
                record.failure_detail = str(exc)
                break
            except Exception as exc:  # backend bug or stub: still fail-stop
                record.status = "failed"
                record.failed_node = node_id
                record.failure_kind = "failed"
                record.failure_detail = "%s: %s" % (type(exc).__name__, exc)
                break
            record.steps.append(step)
            record.executed.append(node_id)
        return record


def build_mock_artifact(record: ExecutionRecord, backend) -> dict:
    """Mock part record covering only executed nodes.

    This is a mock artifact, not a SolidWorks part: it contains the
    executed feature ids, the op log, and the per-node mock readbacks.
    It is written only to the caller's out-dir (see CLI).
    """
    holes = {}
    bends = {}
    if hasattr(backend, "holes"):
        holes = dict(backend.holes)
    if hasattr(backend, "bends"):
        bends = dict(backend.bends)
    return {
        "artifact_version": "feature-tree-mock-part/1",
        "mock_part": True,
        "status": record.status,
        "executed": list(record.executed),
        "op_log": list(getattr(backend, "op_log", [])),
        "holes": holes,
        "bends": bends,
    }
