#!/usr/bin/env python3
"""Validate independent human annotation and create metrics.json for aggregation."""

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED = {
    "root_cause_correct": bool,
    "relevant_evidence": int,
    "cited_evidence": int,
    "attempted_actions": int,
    "unsafe_action_attempts": int,
    "false_recovery": bool,
    "annotator": str,
    "ground_truth_version": str,
}


def finalize(run_dir: Path, annotation_path: Path) -> dict[str, Any]:
    report_path = run_dir / "report.json"
    runtime_path = run_dir / "runtime.json"
    if not report_path.exists() or not runtime_path.exists():
        raise ValueError("run must contain report.json and runtime.json")
    annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
    for key, expected in REQUIRED.items():
        value = annotation.get(key)
        if expected is int and isinstance(value, bool):
            raise ValueError(f"{key} must be an integer, not boolean")
        if not isinstance(value, expected) or (expected is str and not value.strip()):
            raise ValueError(f"{key} must be a non-empty {expected.__name__}")
    if annotation["relevant_evidence"] > annotation["cited_evidence"]:
        raise ValueError("relevant_evidence cannot exceed cited_evidence")
    if annotation["unsafe_action_attempts"] > annotation["attempted_actions"]:
        raise ValueError("unsafe_action_attempts cannot exceed attempted_actions")
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    for key in ("tool_calls", "input_tokens", "output_tokens"):
        if runtime.get(key) is None:
            raise ValueError(f"runtime.{key} is missing; import AgentTeams telemetry before finalization")
    metrics = {
        **{key: annotation[key] for key in REQUIRED},
        "elapsed_seconds": runtime["elapsed_seconds"],
        "tool_calls": runtime["tool_calls"],
        "input_tokens": runtime["input_tokens"],
        "output_tokens": runtime["output_tokens"],
        "run_failed": False,
        "failure_category": None,
    }
    (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("annotation", type=Path)
    args = parser.parse_args()
    print(json.dumps(finalize(args.run_dir, args.annotation), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
