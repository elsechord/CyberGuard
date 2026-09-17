"""Transparent offline rules, not a model or autonomous investigation agent."""
from __future__ import annotations

import math
import posixpath
import shlex

from .evidence import validate_bundle
from .report import SCHEMA, validate_report


def _executable(command):
    if not isinstance(command, str):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    return tokens[0] if tokens else None


def _temporary_path(path):
    normalized = posixpath.normpath(path)
    return any(normalized.startswith(prefix) for prefix in ("/tmp/", "/var/tmp/", "/dev/shm/"))


def _rows(artifact, key):
    value = artifact["data"].get(key, [])
    return value if isinstance(value, list) else []


def analyze_bundle(bundle, *, run_id=None):
    """Correlate measured CPU, executable paths, persistence and inventory.

    The rule recognizes *suspicious persistence*, not malware, mining, an entry
    point or an actor. Missing observations must never become negative evidence.
    """
    validate_bundle(bundle)
    artifacts = [a for a in bundle["artifacts"] if a["status"] == "collected"]
    by_kind = {}
    for artifact in artifacts:
        by_kind.setdefault(artifact["kind"], []).append(artifact)
    findings, actions = [], []

    def finding(kind, claim, status="inconclusive", support=(), contra=(), limitations=()):
        findings.append({"finding_type": kind, "claim": claim, "status": status,
                         "supporting_evidence_ids": list(dict.fromkeys(support)),
                         "contradicting_evidence_ids": list(dict.fromkeys(contra)),
                         "limitations": list(limitations)})

    high_load = []
    for artifact in by_kind.get("processes", []):
        for process in _rows(artifact, "processes"):
            if not isinstance(process, dict):
                continue
            cpu, exe = process.get("cpu_percent"), process.get("exe")
            if (isinstance(cpu, (int, float)) and not isinstance(cpu, bool) and math.isfinite(cpu)
                    and cpu >= 40 and isinstance(exe, str) and exe.startswith("/")
                    and process.get("cpu_observation_status") in ("collected", "measured")):
                high_load.append((artifact, process))
    for artifact, process in high_load:
        exe = process["exe"]
        matches = [(a, e) for a in by_kind.get("persistence", []) for e in _rows(a, "entries")
                   if isinstance(e, dict) and _executable(e.get("command")) == exe and e.get("enabled") is not False]
        inventory = [(a, e) for a in by_kind.get("workload_inventory", []) for e in _rows(a, "entries")
                     if isinstance(e, dict) and e.get("exe") == exe and e.get("authorization") == "approved"]
        observation = f"PID {process.get('pid')} at {exe} measured {process['cpu_percent']}% CPU"
        if matches and _temporary_path(exe):
            refs = [artifact["evidence_id"]] + [a["evidence_id"] for a, _ in matches]
            finding("suspicious_persistence", observation + " and is referenced by a persistence configuration in a temporary-path workload.",
                    "supported", refs, [a["evidence_id"] for a, _ in inventory],
                    ["Path and CPU are triage signals, not proof of malware or cryptomining.",
                     "Configuration does not establish that the scheduler is enabled or caused this process.",
                     "Executable identity, owner intent and observation freshness require independent review."])
            actions.append({"action": "review_persistence_and_preserve_binary", "target": exe,
                            "reason": "Correlated high CPU, temporary executable path and persistence configuration require review before containment.",
                            "evidence_ids": refs, "requires_approval": True})
        elif inventory:
            finding("authorized_workload", observation + " and matches an executable in the supplied approved workload inventory.",
                    "supported", [artifact["evidence_id"]] + [a["evidence_id"] for a, _ in inventory], (),
                    ["A supplied inventory entry is not proof the running binary is authentic or uncompromised.",
                     "High CPU by itself does not justify termination or isolation."])
        else:
            finding("unclassified_workload", observation + "; the available observations do not establish its purpose or authorization.",
                    support=[artifact["evidence_id"]], limitations=["No sufficiently corroborated classification; do not infer mining from CPU alone."])
    if not high_load:
        finding("unclassified_workload", "No workload met this baseline's measured CPU triage rule in the supplied sample.",
                support=[a["evidence_id"] for a in by_kind.get("processes", [])],
                limitations=["A short sample or missing data cannot establish absence of compromise; low-CPU threats are outside this rule."])
    finding("entrypoint", "The initial access vector is not established by this baseline.",
            limitations=["Process/persistence correlation does not prove initial access. Authentication and application events need temporal correlation and provenance checks."])
    finding("attribution", "No responsible organization is established.",
            limitations=["Process paths, shared infrastructure and commodity tools cannot alone identify an organization."])
    unavailable = [a for a in bundle["artifacts"] if a["status"] != "collected"]
    report = {"schema": SCHEMA, "bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["bundle_sha256"],
              "mode": "fixed_workflow", "findings": findings,
              "unknowns": ["Initial access vector", "Responsible organization", "Whether observed executables are malicious"] +
                          [f"Unavailable observation: {a['kind']} ({a['evidence_id']})" for a in unavailable],
              "next_collection": ["Collect authorized authentication and application logs spanning the suspected incident window.",
                                  "Verify executable hashes and workload authorization with the asset owner.",
                                  "Collect scheduler state and process ancestry; repeat collection before any state-changing action."],
              "proposed_actions": actions,
              "method": {"name": "cpu_path_persistence_baseline", "version": 1, "cpu_threshold_percent": 40,
                         "limitations": "Static rules; no model, AgentTeams execution, attribution, remediation or recovery proof."}}
    if run_id is not None:
        report["run_id"] = run_id
    validate_report(report, bundle, expected_mode="fixed_workflow")
    return report
