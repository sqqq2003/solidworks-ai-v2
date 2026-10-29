"""Native editable feature-tree execution interface + mock (module 4).

Public surface: parse_tree / execution_order / convert_plan / Executor /
MockSwApp / RealSwAppAdapter / compute_unfold. See README.md for the IR
format, CLI usage and the relationship with #16, #20 and module 3.
"""

from .executor import Executor, ExecutionRecord, build_mock_artifact
from .mock_backend import MockSwApp, StepFailed, StepPending
from .plan_convert import ConverterError, convert_plan
from .real_backend import RealSwAppAdapter


def __getattr__(name):
    # Lazy: importing unfold here would make `python -m
    # feature_tree.unfold` double-import the module (package __init__
    # runs first, then the module runs as __main__). Lazy loading keeps
    # both `from feature_tree import compute_unfold` and the unfold CLI
    # clean.
    if name == "compute_unfold":
        from .unfold import compute_unfold

        return compute_unfold
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
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
    "compute_unfold",
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
