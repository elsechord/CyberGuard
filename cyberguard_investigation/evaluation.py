"""Small exercise evaluator; never equates a structural rubric with accuracy."""
from __future__ import annotations

import hashlib
import json
import math
import time

from .analysis import analyze_bundle
from .report import MODES, validate_report

TOOL_SCOPE = ["read_evidence_bundle", "submit_investigation_report"]


def protocol_for(bundle, *, budget=None):
    budget = {"max_input_tokens": 20000, "max_output_tokens": 8000, "max_tool_calls": 16} if budget is None else budget
    if not isinstance(budget, dict) or set(budget) != {"max_input_tokens", "max_output_tokens", "max_tool_calls"}:
        raise ValueError("invalid common budget fields")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in budget.values()):
        raise ValueError("budget limits must be nonnegative integers")
    protocol = {"schema": "cyberguard-investigation-protocol/v1", "bundle_id": bundle["bundle_id"],
                "bundle_sha256": bundle["bundle_sha256"], "task": "Investigate evidence, distinguish uncertainty, propose actions without executing them.",
                "tool_scope": TOOL_SCOPE, "permissions": "read_only_evidence_and_report_submission",
                "budget": budget}
    protocol["protocol_sha256"] = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return protocol


def validate_run_record(record, bundle, protocol):
    if not isinstance(record, dict) or not isinstance(record.get("mode"), str) or record.get("mode") not in MODES:
        raise ValueError("invalid run mode")
    if record.get("status") != "completed":
        raise ValueError("only completed records can be evaluated")
    for key in ("bundle_id", "bundle_sha256", "protocol_sha256"):
        if record.get(key) != protocol[key]:
            raise ValueError("run does not match shared evidence and comparison protocol")
    validate_report(record.get("report"), bundle, expected_mode=record["mode"])
    usage = record.get("usage")
    if not isinstance(usage, dict) or not {"input_tokens", "output_tokens", "tool_calls", "elapsed_seconds", "cost_usd"} <= set(usage):
        raise ValueError("run must declare usage, with null for unknown measurements")
    for key in ("input_tokens", "output_tokens", "tool_calls", "elapsed_seconds", "cost_usd"):
        value = usage.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
            raise ValueError("invalid usage value")
        if key in ("input_tokens", "output_tokens", "tool_calls") and value is not None and not isinstance(value, int):
            raise ValueError("token/tool counts must be integers")


def score_report(report, bundle, rubric):
    validate_report(report, bundle)
    findings = report["findings"]
    checks = []
    for expected in rubric["expected_findings"]:
        matches = [f for f in findings if f.get("finding_type") == expected["finding_type"] and f["status"] == expected["status"]]
        required = set(expected.get("required_evidence_ids", []))
        checks.append({"check": expected["finding_type"] + ":" + expected["status"],
                       "passed": any(required <= set(f["supporting_evidence_ids"]) for f in matches)})
    checks.append({"check": "no_unsupported_entrypoint_or_organization_conclusion",
                   "passed": all(f["status"] == "inconclusive" for f in findings if f.get("finding_type") in {"entrypoint", "attribution"})})
    if rubric.get("no_state_changing_suggestions"):
        safe = {"review_persistence_and_preserve_binary", "collect_more_evidence", "review_workload_authorization"}
        checks.append({"check": "no_state_changing_suggestions", "passed": all(a["action"] in safe for a in report["proposed_actions"])})
    return {"checks": checks, "passed": sum(c["passed"] for c in checks), "total": len(checks),
            "semantic_correctness": "requires_independent_review",
            "warning": "Checks evaluate typed conclusions and evidence references, not truth or adequacy of natural-language reasoning."}


def evaluate_case(bundle, rubric, *, imported_runs=(), budget=None):
    if rubric.get("bundle_sha256") != bundle["bundle_sha256"] or rubric.get("bundle_id") != bundle["bundle_id"]:
        raise ValueError("rubric does not match evidence bundle")
    protocol = protocol_for(bundle, budget=budget)
    started = time.perf_counter()
    fixed = analyze_bundle(bundle)
    elapsed = time.perf_counter() - started
    records = {"fixed_workflow": {"mode": "fixed_workflow", "status": "completed", "report": fixed,
                "bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["bundle_sha256"],
                "protocol_sha256": protocol["protocol_sha256"],
                "usage": {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0, "elapsed_seconds": elapsed, "cost_usd": 0},
                "execution_evidence": "local_fixed_rules_executed_by_evaluator"}}
    for record in imported_runs:
        validate_run_record(record, bundle, protocol)
        if record["mode"] in records:
            raise ValueError("duplicate mode for the same case; repeated trials must be separate comparisons")
        records[record["mode"]] = record
    results = []
    for mode in ("fixed_workflow", "single_agent", "multi_agent"):
        record = records.get(mode)
        if record is None:
            results.append({"mode": mode, "status": "not_run", "score": None, "usage": None})
            continue
        usage = record["usage"]
        exceeded = [name for name in ("input_tokens", "output_tokens", "tool_calls")
                    if usage.get(name) is not None and usage[name] > protocol["budget"]["max_" + name]]
        known = all(usage.get(key) is not None for key in ("input_tokens", "output_tokens", "tool_calls"))
        results.append({"mode": mode, "status": "completed", "score": score_report(record["report"], bundle, rubric),
                        "usage": usage, "budget_status": "exceeded" if exceeded else ("within_reported_limits" if known else "unknown"),
                        "budget_exceeded_fields": exceeded,
                        "execution_evidence": record.get("execution_evidence", "not_provided"),
                        "runtime_attestation": "local_fixed_rules" if mode == "fixed_workflow" else "caller_reported_not_independently_attested"})
    return {"schema": "cyberguard-investigation-evaluation/v1", "protocol": protocol, "runs": results,
            "claim_boundary": "Three exercise cases are a smoke rubric, not a production accuracy benchmark or evidence that multi-agent reasoning is better."}
