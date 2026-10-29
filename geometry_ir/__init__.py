"""Geometry IR (geometry-ir/1): feature-tree -> build-ready geometry.

This package is the transport format that closes the honesty gap left
open by bridge CONTRACT.md section 12: build used to reference a plan
only by plan_id, with no complete geometry in the message. The IR is
that geometry, in a versioned, unit-explicit, per-job-parameter form.

The package is pure standard library and never talks to SolidWorks.
Real-machine behaviour is pending_windows_validation; mock results
here are never a SolidWorks measurement.
"""

from __future__ import annotations

from .build import to_build_request
from .ir import IR_VERSION, tree_to_ir
from .mock import mock_roundtrip
from .validate import validate_ir

__all__ = [
    "IR_VERSION",
    "mock_roundtrip",
    "to_build_request",
    "tree_to_ir",
    "validate_ir",
]
