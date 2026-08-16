#!/usr/bin/env python3
"""Aggregate CyberGuard ablation runs without hiding failed or incomplete runs."""

import argparse
import hashlib
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from evaluate import evaluate

NUMERIC_METRICS = (
    "structural_score",
    "root_cause_accuracy",
    "evidence_precision",
    "unsafe_action_rate",
    "false_recovery_rate",
    "elapsed_seconds",
    "tool_calls",
    "input_tokens",
    "output_tokens",
)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    return float(value)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def bootstrap_mean_ci(values: list[float], samples: int = 2000) -> tuple[float, float]:
    """Return a deterministic non-parametric 95% CI for the mean."""
    if not values:
        raise ValueError("cannot bootstrap an empty sample")
    if len(values) == 1:
        return values[0], values[0]
    fingerprint = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).digest()
    generator = random.Random(int.from_bytes(fingerprint[:8], "big"))
    means = [statistics.fmean(generator.choice(values) for _ in values) for _ in range(samples)]
    return _percentile(means, 0.025), _percentile(means, 0.975)


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        raise ValueError("total must be positive")
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = z * ((proportion * (1 - proportion) / total + z * z / (4 * total * total)) ** 0.5) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def summarize(values: list[float | None]) -> dict[str, Any]:
    observed = [float(value) for value in values if value is not None]
    if not observed:
        return {"observations": 0, "missing": len(values), "mean": None, "median": None,
                "stdev": None, "min": None, "max": None, "bootstrap_ci95": [None, None]}
    low, high = bootstrap_mean_ci(observed)
    return {
        "observations": len(observed),
        "missing": len(values) - len(observed),
        "mean": round(statistics.fmean(observed), 4),
        "median": round(statistics.median(observed), 4),
        "stdev": round(statistics.stdev(observed), 4) if len(observed) > 1 else 0.0,
        "min": round(min(observed), 4),
        "max": round(max(observed), 4),
        "bootstrap_ci95": [round(low, 4), round(high, 4)],
    }


def load_runs(results_dir: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for metrics_path in sorted(results_dir.glob("*/*/*/metrics.json")):
        relative = metrics_path.relative_to(results_dir)
        variant, scenario, run_id = relative.parts[:3]
        report_path = metrics_path.with_name("report.json")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        structural = evaluate(report)["score"] if report else 0.0

        relevant = float(metrics.get("relevant_evidence", 0))
        cited = float(metrics.get("cited_evidence", 0))
        actions = float(metrics.get("attempted_actions", 0))
        unsafe = float(metrics.get("unsafe_action_attempts", 0))
        complete = bool(report) and not metrics.get("run_failed", False)
        run = {
            "variant": variant,
            "scenario": scenario,
            "run_id": run_id,
            "structural_score": structural,
            "root_cause_accuracy": 1.0 if metrics.get("root_cause_correct") else 0.0,
            "evidence_precision": relevant / cited if cited else 0.0,
            "unsafe_action_rate": unsafe / actions if actions else None,
            "false_recovery_rate": None if not complete else (1.0 if metrics.get("false_recovery") else 0.0),
            "elapsed_seconds": float(metrics.get("elapsed_seconds", 0)),
            "tool_calls": _optional_float(metrics.get("tool_calls")),
            "input_tokens": _optional_float(metrics.get("input_tokens")),
            "output_tokens": _optional_float(metrics.get("output_tokens")),
            "complete": complete,
            "failure_category": metrics.get("failure_category"),
            "relevant_evidence": relevant,
            "cited_evidence": cited,
            "attempted_actions": actions,
            "unsafe_action_attempts": unsafe,
        }
        runs.append(run)
    return runs


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        grouped[(run["variant"], run["scenario"])].append(run)

    groups: list[dict[str, Any]] = []
    for (variant, scenario), items in sorted(grouped.items()):
        completed = sum(item["complete"] for item in items)
        completion_low, completion_high = wilson_interval(completed, len(items))
        summary: dict[str, Any] = {
            "variant": variant,
            "scenario": scenario,
            "runs": len(items),
            "completed_runs": completed,
            "failed_runs": len(items) - completed,
            "completion_rate": round(completed / len(items), 4),
            "completion_wilson_ci95": [round(completion_low, 4), round(completion_high, 4)],
        }
        for metric in NUMERIC_METRICS:
            summary[metric] = summarize([item[metric] for item in items])
        cited = sum(item["cited_evidence"] for item in items)
        actions = sum(item["attempted_actions"] for item in items)
        summary["pooled_rates"] = {
            "evidence_precision": round(sum(item["relevant_evidence"] for item in items) / cited, 4) if cited else None,
            "unsafe_action_rate": round(sum(item["unsafe_action_attempts"] for item in items) / actions, 4) if actions else None,
        }
        failures: dict[str, int] = defaultdict(int)
        for item in items:
            if item["failure_category"]:
                failures[str(item["failure_category"])] += 1
        summary["failure_categories"] = dict(sorted(failures.items()))
        groups.append(summary)
    return {"total_runs": len(runs), "groups": groups}


def markdown(summary: dict[str, Any]) -> str:
    lines = [
        "| Variant | Scenario | Complete | Root cause | Evidence precision | Unsafe action | False recovery | Structural |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group in summary["groups"]:
        def cell(metric: str) -> str:
            value = group[metric]
            if value["mean"] is None:
                return "NA (n=0)"
            low, high = value["bootstrap_ci95"]
            return f'{value["mean"]:.3f} [{low:.3f}, {high:.3f}] (n={value["observations"]})'
        lines.append(
            f'| {group["variant"]} | {group["scenario"]} | {group["completed_runs"]}/{group["runs"]} '
            f'| {cell("root_cause_accuracy")} | {cell("evidence_precision")} '
            f'| {cell("unsafe_action_rate")} | {cell("false_recovery_rate")} '
            f'| {cell("structural_score")} |'
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=Path("benchmark/results"))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()

    runs = load_runs(args.results)
    if not runs:
        raise SystemExit(f"No benchmark runs found under {args.results}")
    summary = aggregate(runs)
    rendered_json = json.dumps(summary, ensure_ascii=False, indent=2)
    rendered_markdown = markdown(summary)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered_json + "\n", encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(rendered_markdown, encoding="utf-8")
    print(rendered_markdown)


if __name__ == "__main__":
    main()
