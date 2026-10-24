"""Command-line entry point for feature-tree execution (mock).

Usage:
  python -m feature_tree.cli <plan-or-tree.json> --out-dir out
  python -m feature_tree.cli <plan.json> --out-dir out --job-params job.json
  python -m feature_tree.cli <tree.json> --out-dir out --tree-out tree.json

Input auto-detection:
* a document with plan_version "dxf-extract/1" is a module 3 plan and
  is converted (job params, when supplied, fill bend/hole values;
  missing job params turn affected nodes pending, never defaults);
* a document with tree_version "feature-tree/1" is used directly.

Outputs (only inside --out-dir; the input file is never modified):
* execution.json : the execution record (steps, status, evidence).
* mock_part.json : the mock artifact record (executed nodes only).

Exit codes (mirroring module 3's convention):
* 0 = execution completed with status ok.
* 1 = execution stopped (a node pending or failed); the record is
  still written, and later nodes have no step or artifact entry.
* 2 = input error (missing file, malformed JSON, unsupported version,
  or tree validation error: duplicate id, unknown type, missing
  dependency, dependency cycle).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .executor import Executor, build_mock_artifact
from .mock_backend import MockSwApp
from .plan_convert import ConverterError, convert_plan
from .tree import TreeError, parse_tree


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("document must be a JSON object")
    return data


def run(input_path: str, out_dir: str, job_params_path: str | None = None,
        tree_out_path: str | None = None) -> int:
    try:
        document = _load_json(input_path)
    except (OSError, ValueError) as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2
    job_params = None
    if job_params_path:
        try:
            job_params = _load_json(job_params_path)
        except (OSError, ValueError) as exc:
            print("input error (job params): %s" % exc, file=sys.stderr)
            return 2
    try:
        if document.get("plan_version") == "dxf-extract/1":
            tree = convert_plan(document, job_params)
        elif document.get("tree_version") == "feature-tree/1":
            tree = parse_tree(document)
        else:
            print(
                "input error: document is neither dxf-extract/1 nor "
                "feature-tree/1",
                file=sys.stderr,
            )
            return 2
    except (ConverterError, TreeError) as exc:
        print("input error: %s" % exc, file=sys.stderr)
        return 2

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if tree_out_path:
        Path(tree_out_path).write_text(
            json.dumps(tree.to_dict(), indent=2), encoding="utf-8"
        )
    backend = MockSwApp()
    record = Executor(backend).run(tree)
    artifact = build_mock_artifact(record, backend)
    (out / "execution.json").write_text(
        json.dumps(record.to_dict(), indent=2), encoding="utf-8"
    )
    (out / "mock_part.json").write_text(
        json.dumps(artifact, indent=2), encoding="utf-8"
    )
    if record.status == "ok":
        print(
            "ok: executed %d node(s): %s"
            % (len(record.executed), ", ".join(record.executed))
        )
        return 0
    print(
        "stopped at %s (%s): %s"
        % (record.failed_node, record.failure_kind, record.failure_detail)
    )
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute a feature tree (mock backend)."
    )
    parser.add_argument("input", help="plan.json (dxf-extract/1) or tree JSON")
    parser.add_argument("--out-dir", required=True,
                        help="output directory (only this dir is written)")
    parser.add_argument("--job-params",
                        help="optional per-job parameters JSON")
    parser.add_argument("--tree-out",
                        help="optional path to write the converted tree JSON")
    args = parser.parse_args(argv)
    return run(args.input, args.out_dir, args.job_params, args.tree_out)


if __name__ == "__main__":
    raise SystemExit(main())
