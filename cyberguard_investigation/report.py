"""Evidence-bound report contracts. Validation checks structure, not truth of prose."""
from __future__ import annotations

import html
import re

from .evidence import validate_bundle

SCHEMA = "cyberguard-investigation-report/v1"
MODES = {"fixed_workflow", "single_agent", "multi_agent"}


def _strings(value, label, *, nonempty=False):
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError(f"{label} must be a bounded string array")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 12000 for v in value):
        raise ValueError(f"{label} contains invalid text")
    if nonempty and not value:
        raise ValueError(f"{label} cannot be empty")


def validate_report(report, bundle, *, expected_mode=None):
    """Reject mixed bundles, unavailable support and unbound modes; return None.

    A valid report can still be factually wrong. An external reviewer/evaluator
    must assess whether each quoted observation actually supports its claim.
    """
    validate_bundle(bundle)
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("unsupported report schema")
    if (report.get("bundle_id") != bundle["bundle_id"] or
            report.get("bundle_sha256") != bundle["bundle_sha256"]):
        raise ValueError("report is not bound to this evidence bundle")
    mode = report.get("mode")
    if not isinstance(mode, str) or mode not in MODES or (expected_mode is not None and mode != expected_mode):
        raise ValueError("report mode mismatch")
    if "run_id" in report and (not isinstance(report["run_id"], str) or not report["run_id"].strip()):
        raise ValueError("invalid run_id")
    available = {a["evidence_id"] for a in bundle["artifacts"] if a["status"] == "collected"}
    findings = report.get("findings")
    if not isinstance(findings, list) or not 1 <= len(findings) <= 1000:
        raise ValueError("report requires bounded findings")
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("invalid finding")
        _strings([finding.get("claim")], "claim", nonempty=True)
        if finding.get("status") not in ("supported", "refuted", "inconclusive"):
            raise ValueError("invalid finding status")
        if "finding_type" in finding:
            _strings([finding["finding_type"]], "finding_type")
        for key in ("supporting_evidence_ids", "contradicting_evidence_ids", "limitations"):
            _strings(finding.get(key), key)
        for key in ("supporting_evidence_ids", "contradicting_evidence_ids"):
            refs = finding[key]
            if len(set(refs)) != len(refs) or not set(refs) <= available:
                raise ValueError("unknown, duplicate or unavailable evidence reference")
        if finding["status"] == "supported" and not finding["supporting_evidence_ids"]:
            raise ValueError("supported claim requires collected evidence")
        if finding["status"] == "refuted" and not finding["contradicting_evidence_ids"]:
            raise ValueError("refuted claim requires collected evidence")
        if finding["status"] == "inconclusive" and not finding["limitations"]:
            raise ValueError("inconclusive claim must explain its limitation")
    for key in ("unknowns", "next_collection"):
        _strings(report.get(key), key)
    actions = report.get("proposed_actions")
    if not isinstance(actions, list) or len(actions) > 100:
        raise ValueError("invalid proposed_actions")
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("invalid proposed action")
        for key in ("action", "target", "reason"):
            _strings([action.get(key)], key)
        _strings(action.get("evidence_ids"), "action evidence_ids", nonempty=True)
        if not set(action["evidence_ids"]) <= available:
            raise ValueError("action cites unknown or unavailable evidence")
        if action.get("requires_approval") is not True:
            raise ValueError("actions are suggestions requiring separate approval")


def render_markdown(report):
    """Escape all untrusted fields; preserve original text only in the JSON."""
    def safe(value):
        value = html.escape(" ".join(str(value).split()), quote=True)
        return re.sub(r"([\\`*_{}\[\]()#+.!|\-])", r"\\\1", value)

    lines = ["# CyberGuard investigation", "", f"Mode: {safe(report['mode'])}",
             f"Evidence bundle: {safe(report['bundle_id'])}", f"SHA-256: {safe(report['bundle_sha256'])}", "",
             "This report proposes actions only. It does not execute or authorize them.", ""]
    for finding in report["findings"]:
        lines.extend([f"## {safe(finding.get('finding_type', 'Finding'))} — {safe(finding['status'])}", "",
                      safe(finding["claim"]), "", "Support: " + (", ".join(safe(v) for v in finding["supporting_evidence_ids"]) or "none"),
                      "Contradiction: " + (", ".join(safe(v) for v in finding["contradicting_evidence_ids"]) or "none"), ""])
        lines.extend("- Limitation: " + safe(value) for value in finding["limitations"])
        lines.append("")
    for title, key in (("Unknowns", "unknowns"), ("Next collection", "next_collection")):
        lines.extend([f"## {title}", ""] + ["- " + safe(item) for item in report[key]] + [""])
    lines.extend(["## Proposed actions", ""])
    for action in report["proposed_actions"]:
        lines.append(f"- {safe(action['action'])} — {safe(action['target'])}: {safe(action['reason'])} (separate approval required)")
    return "\n".join(lines) + "\n"
