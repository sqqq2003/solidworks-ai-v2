"""Whole-machine parameter dependency, assembly-relation and conflict
precheck engine (Issue #25 expansion module 5).

Offline, pure Python standard library. See README.md for the input
format, the CLI, and the honesty boundaries. All Windows / SolidWorks
behaviour is pending_windows_validation.
"""

from .engine import (
    FORMAT_VERSION,
    REPORT_VERSION,
    CycleError,
    DuplicateNameError,
    InputError,
    precheck,
)

__all__ = [
    "FORMAT_VERSION",
    "REPORT_VERSION",
    "CycleError",
    "DuplicateNameError",
    "InputError",
    "precheck",
]
