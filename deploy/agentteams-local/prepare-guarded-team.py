#!/usr/bin/env python3
"""Prepare fresh, sleeping AgentTeams identities and per-role guard routes.

Offline only: no Docker/API/model call, secret generation or deployment. JSON
documents are valid YAML inputs to `agt apply -f`. Secrets are injected later.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[2]

ROLE_SKILLS = {
    "investigator": ["endpoint-forensics", "hypothesis-testing"],
    "planner": ["response-planning", "incident-reporting"],
    "verifier": ["recovery-verification", "incident-reporting"],
}
OLD_NAMES = {"endpoint-forensics", "response-planner", "recovery-verifier", "cyberguard-investigation"}


def prepare(out, run_id, prefix, model, guard_url):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,100}", run_id):
        raise ValueError("Invalid immutable run ID")
    if not re.fullmatch(r"cg-[a-z0-9][a-z0-9-]{2,34}", prefix) or prefix in OLD_NAMES:
        raise ValueError("Use a new short cg-* name prefix")
    parsed = urlsplit(guard_url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Guard must be a local Docker HTTP service without credentials")
    if not parsed.hostname or not parsed.hostname.endswith(".agentteams.local") or parsed.path.rstrip("/") != "/v1":
        raise ValueError("Guard URL must use a .agentteams.local Docker alias and /v1")
    port = parsed.port or 80
    roles = {}
    documents = {}
    for role, skills in ROLE_SKILLS.items():
        name = f"{prefix}-{role}"
        provider = name
        alias = name + "-model"
        route_prefix = f"/cg-guard/{name}"
        roles[role] = {"worker": name, "provider": provider, "route": name,
                       "model_alias": alias, "route_prefix": route_prefix, "service_source": name + "-guard"}
        documents[name + ".service-source.json"] = {"type": "dns", "name": name + "-guard", "domain": parsed.hostname,
            "port": port, "protocol": "http", "properties": {}, "authN": {"enabled": False}}
        documents[name + ".worker.json"] = {
            "apiVersion": "agentteams.io/v1beta1", "kind": "Worker", "metadata": {"name": name},
            "spec": {"workerName": name, "model": alias, "modelProvider": provider,
                     "runtime": "qwenpaw", "state": "Sleeping", "skills": skills,
                     "mcpServers": [
                         {"name": "mcp-cyberguard-investigation-" + suffix, "transport": "http",
                          "url": "http://aigw-local.agentteams.io:8080/mcp-servers/mcp-cyberguard-investigation-" + suffix + "/mcp"}
                         for suffix in ("readonly", "report")],
                     "agents": f"Bound run: {run_id}. Role: {role}. Only exercise evidence assigned to this run may be analyzed. "
                               "The external harness sequences roles; do not create rooms, delegate, self-message, spawn agents or resume other runs. "
                               "Use only the investigation evidence/report tools. Do not execute response actions or request credentials. "
                               "An error or denial is a blocker, not permission to retry with another identity or route."}}
        documents[name + ".provider.template.json"] = {
            "type": "openai", "name": provider, "tokens": ["INJECT_ROLE_GUARD_KEY_AT_APPLY_TIME"],
            "version": 0, "protocol": "openai/v1", "tokenFailoverConfig": {"enabled": False},
            "rawConfigs": {"openaiCustomUrl": guard_url.rstrip("/"), "openaiCustomServiceName": name + "-guard.dns",
                           "openaiCustomServicePort": port, "agentteamsMode": True}}
        documents[name + ".route.json"] = {
            "name": name, "domains": ["aigw-local.agentteams.io", "agentteams-controller"],
            "pathPredicate": {"matchType": "PRE", "matchValue": route_prefix, "caseSensitive": True},
            "upstreams": [{"provider": provider, "weight": 100, "modelMapping": {}}],
            "authConfig": {"enabled": True, "allowedCredentialTypes": ["key-auth"],
                           "allowedConsumers": ["worker-" + name]}}
    documents["team.json"] = {"apiVersion": "agentteams.io/v1beta1", "kind": "Team", "metadata": {"name": prefix},
        "spec": {"description": f"Guarded serial integration {run_id}; harness orchestrated, not autonomous roomflow",
                 "peerMentions": False, "heartbeatEvery": "",
                 "workerMembers": [{"name": value["worker"], "role": "team_leader" if role == "planner" else "worker"}
                                   for role, value in roles.items()]}}
    documents["manifest.json"] = {"schema": "cyberguard-guarded-team-plan/v1", "run_id": run_id,
        "team": prefix, "canonical_model": model, "guard_url": guard_url, "roles": roles,
        "status": "prepared_not_applied", "model_calls": 0, "orchestration": "external_serial_harness",
        "required_preflight": ["fresh_identity_inventory", "guard_disarmed", "model_provider_route_isolation",
            "builtin_tools_disabled", "actual_inference_tool_schema_allowlist", "mcp_policy_actual_context",
            "provider_secrets_absent_from_workers", "localhost_ports", "blocked_direct_provider_probe"]}
    out.mkdir(parents=True, exist_ok=False)
    for name, body in documents.items():
        (out / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for role, entry in roles.items():
        package = out / (entry["worker"] + ".zip")
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({"version": "1.1.0", "worker": {
                "suggested_name": entry["worker"], "runtime": "qwenpaw", "model": entry["model_alias"],
                "skills": ROLE_SKILLS[role]}}))
            for skill in ROLE_SKILLS[role]:
                archive.write(ROOT / "skills" / skill / "SKILL.md", f"skills/{skill}/SKILL.md")
    checksum_names = list(documents) + [entry["worker"] + ".zip" for entry in roles.values()]
    (out / "SHA256SUMS").write_text("".join(hashlib.sha256((out / name).read_bytes()).hexdigest() + "  " + name + "\n"
                                             for name in sorted(checksum_names)), encoding="ascii")
    return documents["manifest.json"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--name-prefix", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--guard-url", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.out, args.run_id, args.name_prefix, args.model, args.guard_url), indent=2))


if __name__ == "__main__":
    main()
