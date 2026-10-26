"""Native editable feature-tree execution interface + mock (module 4).

Public surface: parse_tree / execution_order / convert_plan / Executor /
MockSwApp / RealSwAppAdapter. See README.md for the IR format, CLI
usage and the relationship with #16, #20 and module 3.
"""

from .executor import Executor, ExecutionRecord, build_mock_artifact
from .mock_backend import MockSwApp, StepFailed, StepPending
from .plan_convert import ConverterError, convert_plan
from .real_backend import RealSwAppAdapter
from .tree import (
    CycleError,
    DuplicateIdError,
    FeatureNode,
    FeatureTree,
    MissingDependencyError,
    TreeError,
    UnknownTypeError,
    execution_order,
    parse_tree,
)

__all__ = [
    "Executor",
    "ExecutionRecord",
    "build_mock_artifact",
    "MockSwApp",
    "StepFailed",
    "StepPending",
    "ConverterError",
    "convert_plan",
    "RealSwAppAdapter",
    "CycleError",
    "DuplicateIdError",
    "FeatureNode",
    "FeatureTree",
    "MissingDependencyError",
    "TreeError",
    "UnknownTypeError",
    "execution_order",
    "parse_tree",
]
