#!/usr/bin/env python3
"""Fail-closed structural review of raw AgentTeams run evidence.

JSON pointers accommodate actual exporter fields without inventing an AT API.
Local hashes and operator-provided mappings DO NOT attest source authenticity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROLES = {
    "endpoint-forensics": {"endpoint-forensics", "hypothesis-testing"},
    "response-planner": {"response-planning", "incident-reporting"},
    "recovery-verifier": {"recovery-verification", "incident-reporting"},
}
TOOLS = {"read_investigation_evidence", "read_investigation_reports", "submit_investigation_report"}


def pointer(document, path):
    if not isinstance(path, str) or (path and not path.startswith("/")):
        raise ValueError("invalid JSON pointer")
    value = document
    for key in path.split("/")[1:] if path else []:
        key = key.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise ValueError("invalid JSON pointer array index")
            value = value[int(key)]
        else:
            value = value[key]
    return value


def validate(pack: dict, root: Path) -> dict:
    issues = []
    documents = {}
    kinds = {}
    root = root.resolve()
    try:
        if pack.get("schema") != "cyberguard-agentteams-run-evidence/v1":
            raise ValueError("unsupported evidence schema")
        if pack.get("status") == "not_run":
            return {"valid": False, "status": "not_run", "runtime_attestation": "not_attested",
                    "issues": ["No real AgentTeams run was supplied"]}
        if pack.get("mode") not in {"single_agent", "multi_agent"}:
            raise ValueError("only actual agent runs belong in this validator")
        if not re.fullmatch(r"[a-f0-9]{64}", str(pack.get("bundle_sha256", ""))):
            raise ValueError("invalid bundle SHA256")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,127}", str(pack.get("run_id", ""))):
            raise ValueError("invalid run_id")
        budget = pack["budget"]
        if any(type(budget.get(key)) is not int or budget[key] <= 0 for key in
               ("max_input_tokens", "max_output_tokens", "max_tool_calls")):
            raise ValueError("positive integer budgets required")
        for item in pack.get("sources", []):
            sid = item["id"]
            if sid in documents:
                raise ValueError("duplicate source id")
            path = (root / item["path"]).resolve()
            if root not in path.parents or not path.is_file():
                raise ValueError("source path must remain inside evidence directory")
            raw = path.read_bytes()
            if len(raw) > 20_000_000 or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("source size/hash validation failed")
            documents[sid] = json.loads(raw)
            kinds[sid] = item["kind"]

        def ref(value, kind):
            if not isinstance(value, dict) or set(value) != {"source", "pointer"}:
                raise ValueError("runtime proof must be a source + JSON pointer, not a self-reported literal")
            sid = value["source"]
            if kinds.get(sid) != kind:
                raise ValueError(f"proof requires source kind {kind}")
            return pointer(documents[sid], value["pointer"])

        def nonempty(value):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("missing native identifier")
            return value

        task = pack["task"]
        task_id = nonempty(ref(task["task_id"], "native_task"))
        if ref(task["run_id"], "native_task") != pack["run_id"]:
            raise ValueError("task run binding mismatch")
        if ref(task["bundle_sha256"], "native_task") != pack["bundle_sha256"]:
            raise ValueError("task bundle binding mismatch")
        if ref(task["status"], "native_task") not in {"Completed", "Succeeded", "completed", "succeeded"}:
            raise ValueError("task is not recorded as completed")
        workers = {}
        for item in pack["workers"]:
            wid = nonempty(ref(item["worker_id"], "native_workers"))
            if wid in workers or item["role"] not in ROLES:
                raise ValueError("duplicate worker or unknown role")
            skills = ref(item["skills"], "native_workers")
            if not isinstance(skills, list) or not ROLES[item["role"]].issubset(set(skills)):
                raise ValueError("worker missing actual skill configuration")
            tools = ref(item["tools"], "native_workers")
            if not isinstance(tools, list) or set(tools) != {"mcp-cyberguard-investigation-readonly", "mcp-cyberguard-investigation-report"}:
                raise ValueError("worker tool permissions differ from investigation-only configuration")
            workers[wid] = {"role": item["role"], "skills": set(skills)}
        if pack["mode"] == "multi_agent" and (len(workers) != 3 or {w["role"] for w in workers.values()} != set(ROLES)):
            raise ValueError("multi_agent requires three distinct role-bound workers")
        if pack["mode"] == "single_agent" and (len(workers) != 1 or not set.union(*ROLES.values()).issubset(next(iter(workers.values()))["skills"])):
            raise ValueError("single agent must have the same combined skills")

        called = set()
        all_call_ids = set()
        submitted = False
        for call in pack["tool_calls"]:
            wid = ref(call["worker_id"], "native_tool_events")
            if wid not in workers or ref(call["task_id"], "native_tool_events") != task_id:
                raise ValueError("tool call worker/task mismatch")
            if ref(call["run_id"], "native_tool_events") != pack["run_id"] or ref(call["bundle_sha256"], "native_tool_events") != pack["bundle_sha256"]:
                raise ValueError("tool call run/bundle mismatch")
            tool = ref(call["tool"], "native_tool_events")
            cid = nonempty(ref(call["call_id"], "native_tool_events"))
            if tool not in TOOLS or cid in all_call_ids:
                raise ValueError("unallowed tool or duplicate call receipt")
            all_call_ids.add(cid)
            if tool == "read_investigation_evidence":
                called.add(wid)
            submitted |= tool == "submit_investigation_report"
        if called != set(workers) or not submitted:
            raise ValueError("every worker must read original evidence; report submission receipt is required")

        lifecycle = {wid: {} for wid in workers}
        seen_events = set()
        for event in pack["skill_events"]:
            wid = ref(event["worker_id"], "native_skill_events")
            if wid not in workers or ref(event["task_id"], "native_skill_events") != task_id:
                raise ValueError("skill event worker/task mismatch")
            skill = ref(event["skill"], "native_skill_events")
            eid = nonempty(ref(event["event_id"], "native_skill_events"))
            phase = ref(event["phase"], "native_skill_events")
            if skill not in workers[wid]["skills"] or eid in seen_events:
                raise ValueError("skill not bound or duplicate lifecycle receipt")
            seen_events.add(eid)
            lifecycle[wid].setdefault(skill, set()).add(phase)
        if any(not any({"loaded", "invoked"}.issubset(phases) for phases in skills.values())
               for skills in lifecycle.values()):
            raise ValueError("skill configuration alone does not prove load/invocation")

        usage = pack["usage"]
        if ref(usage["task_id"], "native_model_usage") != task_id:
            raise ValueError("model usage task mismatch")
        tokens = [ref(usage[name], "native_model_usage") for name in ("input_tokens", "output_tokens")]
        if any(isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in tokens) or sum(tokens) <= 0:
            raise ValueError("actual positive model token usage is required")
        nonempty(ref(usage["model"], "native_model_usage"))
        if tokens[0] > budget["max_input_tokens"] or tokens[1] > budget["max_output_tokens"] or len(all_call_ids) > budget["max_tool_calls"]:
            raise ValueError("recorded aggregate usage exceeds declared budget")
    except (KeyError, TypeError, ValueError, IndexError, OSError) as exc:
        issues.append(str(exc))
    return {"valid": not issues, "status": "structurally_complete_not_attested" if not issues else "incomplete",
            "runtime_attestation": "not_attested", "issues": issues,
            "limitations": ["Source kinds and JSON pointer mappings are operator supplied.",
                            "Local SHA256 checks prove unchanged files, not authentic AgentTeams execution.",
                            "Inspect originals and runtime collection provenance before making live-run claims."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = validate(json.loads(args.manifest.read_text(encoding="utf-8")), args.manifest.parent)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
