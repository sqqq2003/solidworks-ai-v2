"""Issue #6 module 1: independent QL-5050PX parameter configuration.

QL-5050PX is a DWG-only packing machine and is NOT the A01 / GT-ZX assembly.
This package keeps its own spec, graph, solver and CLI on top of the shared
offline preflight primitives in ``a01.py``. It never copies confirmed GT-ZX
or A01 equation values; the 1800x900x1500 envelope stays a target placeholder.
"""

from .config import DEFAULT_ENVELOPE_MM, SPEC_PATH, load_spec, with_envelope
from .graph import assert_documented, iter_edges
from .solver import solve, solve_spec

__all__ = [
    "DEFAULT_ENVELOPE_MM",
    "SPEC_PATH",
    "assert_documented",
    "iter_edges",
    "load_spec",
    "solve",
    "solve_spec",
    "with_envelope",
]
