#!/usr/bin/env python3
"""Fail closed when benchmark evidence is incomplete or conditions drift."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scenario_hash(scenario: dict[str, Any]) -> str:
    canonical = json.dumps(scenario, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_text(canonical)


def audit(results: Path, variants_path: Path, scenarios_dir: Path, require_complete: bool = True) -> dict[str, Any]:
    config = json.loads(variants_path.read_text(encoding="utf-8"))
    variants = {item["id"]: item for item in config["variants"]}
    scenarios = {
        scenario_id: json.loads((scenarios_dir / f"{scenario_id}.json").read_text(encoding="utf-8"))
        for scenario_id in config["scenarios"]
    }
    expected_runs = int(config["repetitions"])
    issues: list[str] = []
    counts: Counter[tuple[str, str]] = Counter()
    conditions: defaultdict[str, set[Any]] = defaultdict(set)
    run_ids: set[str] = set()

    metric_paths = sorted(results.glob("*/*/*/metrics.json"))
    for metrics_path in metric_paths:
        relative = metrics_path.relative_to(results)
        variant_id, scenario_id, run_id = relative.parts[:3]
        run_dir = metrics_path.parent
        counts[(variant_id, scenario_id)] += 1
        if run_id in run_ids:
            issues.append(f"duplicate run_id: {run_id}")
        run_ids.add(run_id)
        if variant_id not in variants:
            issues.append(f"unknown variant: {variant_id}/{scenario_id}/{run_id}")
            continue
        if scenario_id not in scenarios:
            issues.append(f"unknown scenario: {variant_id}/{scenario_id}/{run_id}")
            continue
        provenance_path = run_dir / "provenance.json"
        prompt_path = run_dir / "prompt.txt"
        if not provenance_path.exists() or not prompt_path.exists():
            issues.append(f"missing provenance or prompt: {variant_id}/{scenario_id}/{run_id}")
            continue
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        expected = {
            "run_id": run_id,
            "variant": variant_id,
            "scenario_id": scenario_id,
            "disabled_capabilities": variants[variant_id].get("disabled_capabilities", []),
            "scenario_sha256": _scenario_hash(scenarios[scenario_id]),
            "prompt_sha256": _hash_text(prompt_path.read_text(encoding="utf-8")),
        }
        for key, value in expected.items():
            if provenance.get(key) != value:
                issues.append(f"provenance mismatch {key}: {variant_id}/{scenario_id}/{run_id}")
        for key in ("cyberguard_version", "agentteams_version", "model_id", "temperature"):
            value = provenance.get(key)
            if value is None or value == "":
                issues.append(f"missing provenance {key}: {variant_id}/{scenario_id}/{run_id}")
            else:
                conditions[key].add(value)
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        if not metrics.get("run_failed", False):
            for required in ("report.json", "runtime.json", "annotation.json"):
                if not (run_dir / required).exists():
                    issues.append(f"successful run missing {required}: {variant_id}/{scenario_id}/{run_id}")
            for label in ("annotator", "ground_truth_version"):
                if not metrics.get(label):
                    issues.append(f"successful run missing {label}: {variant_id}/{scenario_id}/{run_id}")

    for key, values in conditions.items():
        if len(values) > 1:
            issues.append(f"condition drift for {key}: {sorted(map(str, values))}")
    expected_groups = {(variant, scenario) for variant in variants for scenario in scenarios}
    if require_complete:
        for group in sorted(expected_groups):
            if counts[group] != expected_runs:
                issues.append(f"expected {expected_runs} runs for {group[0]}/{group[1]}, found {counts[group]}")
    for variant, scenario in sorted(set(counts) - expected_groups):
        issues.append(f"unexpected result group: {variant}/{scenario}")

    return {
        "valid": not issues,
        "require_complete": require_complete,
        "expected_groups": len(expected_groups),
        "expected_runs_per_group": expected_runs,
        "observed_runs": len(metric_paths),
        "group_counts": {f"{variant}/{scenario}": counts[(variant, scenario)] for variant, scenario in sorted(expected_groups)},
        "fixed_conditions": {key: sorted(map(str, values)) for key, values in sorted(conditions.items())},
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=Path("benchmark/results"))
    parser.add_argument("--variants", type=Path, default=Path("benchmark/variants.json"))
    parser.add_argument("--scenarios", type=Path, default=Path("scenarios"))
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.results, args.variants, args.scenarios, not args.allow_partial)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
