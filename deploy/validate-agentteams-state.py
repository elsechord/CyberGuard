#!/usr/bin/env python3
"""Validate CyberGuard AgentTeams bootstrap state against live CR snapshots.

The Manager result is useful deployment evidence, but it is not an authority for
runtime permissions.  In particular, a Manager can report that it installed a
Skill or registered an MCP server while the Worker CR has neither binding.  This
validator therefore treats Worker CRs as the source of truth for role Skills and
MCP clients.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EXPECTED = {
    "alert-fusion": ({"alert-triage", "hypothesis-testing"}, {"cyberguard-readonly"}),
    "threat-intel": ({"threat-intel-enrichment", "hypothesis-testing"}, {"cyberguard-readonly"}),
    "network-hunter": ({"network-hunting", "boundary-defense", "hypothesis-testing"}, {"cyberguard-readonly"}),
    "endpoint-forensics": ({"endpoint-forensics", "hypothesis-testing"}, {"cyberguard-readonly"}),
    "response-planner": ({"response-planning", "incident-reporting"}, {"cyberguard-readonly", "cyberguard-response"}),
    "controlled-responder": ({"controlled-response"}, {"cyberguard-response"}),
    "recovery-verifier": ({"recovery-verification", "incident-reporting"}, {"cyberguard-readonly"}),
}
ROOM_ID = re.compile(r"^![^:\s]+:[^\s]+$")

# AgentTeams versions and exporters use slightly different spellings.  Keep the
# aliases deliberately narrow: configuration found in arbitrary status/log text
# is *not* accepted as a runtime binding.
SKILL_KEYS = {
    "skills", "skillNames", "skill_names", "skillRefs", "skill_refs",
    "installedSkills", "installed_skills",
}
TOOL_KEYS = {
    "tools", "toolServices", "tool_services", "mcpClients", "mcp_clients",
    "mcpServers", "mcp_servers", "mcpRefs", "mcp_refs", "mcp",
}
CONFIG_KEYS = {"spec", "config", "configuration", "agent", "worker"}
ENV_SKILL_KEYS = {"SKILLS", "SKILL_NAMES", "SKILL_REFS"}
ENV_TOOL_KEYS = {"MCP_CLIENTS", "MCP_SERVERS", "MCP_REFS", "TOOL_SERVICES"}


def resource_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        metadata = value.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
            names.add(metadata["name"])
        for child in value.values():
            names.update(resource_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(resource_names(child))
    return names


def _normalise_tool(name: str) -> str:
    """Map the AgentTeams MCP client naming convention to CyberGuard names."""
    normalized = name.strip()
    if normalized.startswith("mcp-"):
        normalized = normalized[4:]
    return normalized


def _names(value: Any) -> set[str]:
    """Extract names from common Kubernetes/AgentTeams reference shapes."""
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip()}
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_names(item))
        return result
    if not isinstance(value, dict):
        return set()
    result: set[str] = set()
    for key in ("name", "ref", "id", "skill", "client", "server"):
        if isinstance(value.get(key), str):
            result.add(value[key].strip())
    metadata = value.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
        result.add(metadata["name"].strip())
    return result


def _bindings_from_config(value: Any) -> tuple[set[str], set[str]]:
    """Read explicit runtime Skill/MCP bindings from a single Worker CR.

    Only the CR body and its ``spec``/``config`` sections are inspected.  We do
    not recursively scan ``status`` or log records, as those can mention a tool
    that was never bound to the Worker.
    """
    skills: set[str] = set()
    tools: set[str] = set()

    def visit(node: Any, allow_config: bool = True) -> None:
        if not isinstance(node, dict):
            return
        for key, child in node.items():
            if key == "status":
                continue
            if key in SKILL_KEYS:
                skills.update(_names(child))
                continue
            if key in TOOL_KEYS:
                tools.update(_normalise_tool(name) for name in _names(child))
                continue
            if key in {"env", "environment"} and isinstance(child, list):
                for entry in child:
                    if not isinstance(entry, dict):
                        continue
                    env_name = entry.get("name")
                    env_value = entry.get("value")
                    if env_name in ENV_SKILL_KEYS:
                        skills.update(_names(env_value))
                    if env_name in ENV_TOOL_KEYS:
                        tools.update(_normalise_tool(name) for name in _names(env_value))
                continue
            if allow_config and (key in CONFIG_KEYS or key in {"containers", "template"}):
                if isinstance(child, list):
                    for entry in child:
                        visit(entry)
                else:
                    visit(child)

    visit(value)
    return skills, tools


def worker_crs(snapshot: Any) -> dict[str, list[dict[str, Any]]]:
    """Return Worker CR objects keyed by name, tolerating list/items wrappers."""
    found: dict[str, list[dict[str, Any]]] = {name: [] for name in EXPECTED}

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        metadata = node.get("metadata")
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if name in found:
            found[name].append(node)
            return
        for child in node.values():
            visit(child)

    visit(snapshot)
    return found


def validate_worker_bindings(workers_snapshot: Any) -> tuple[list[str], dict[str, dict[str, list[str]]]]:
    """Validate actual Worker CR Skill/MCP bindings, independent of Manager text."""
    issues: list[str] = []
    observed: dict[str, dict[str, list[str]]] = {}
    records = worker_crs(workers_snapshot)
    cyberguard_skills = set().union(*(skills for skills, _ in EXPECTED.values()))
    for name, (required_skills, required_tools) in EXPECTED.items():
        matches = records[name]
        if len(matches) != 1:
            issues.append(f"Worker CR for {name} must appear exactly once, found {len(matches)}")
            continue
        skills, tools = _bindings_from_config(matches[0])
        observed[name] = {"skills": sorted(skills), "tools": sorted(tools)}
        # Built-in AgentTeams Skills may coexist; only CyberGuard Skill bindings
        # are compared.  MCP clients are privileges, so their set must be exact.
        actual_cyberguard_skills = skills & cyberguard_skills
        if actual_cyberguard_skills != required_skills:
            issues.append(
                f"{name} live Worker CR skill binding mismatch: "
                f"expected {sorted(required_skills)}, got {sorted(actual_cyberguard_skills)}"
            )
        if tools != required_tools:
            issues.append(
                f"{name} live Worker CR tool boundary mismatch: "
                f"expected {sorted(required_tools)}, got {sorted(tools)}"
            )
    return issues, observed


def validate(manifest: dict[str, Any], workers_snapshot: Any | None = None,
             teams_snapshot: Any | None = None) -> dict[str, Any]:
    issues: list[str] = []
    if manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
        issues.append("manager manifest is not schema_version=1 status=complete")
    team = manifest.get("team", {})
    if team.get("name") != "cyberguard-soc":
        issues.append("team name must be cyberguard-soc")
    if not ROOM_ID.fullmatch(str(team.get("room_id", ""))):
        issues.append("team room_id is not an exact Matrix room ID")
    if set(manifest.get("tool_services", [])) != {"cyberguard-readonly", "cyberguard-response"}:
        issues.append("both CyberGuard tool services must be registered")
    if manifest.get("approval_secret_exposed") is not False:
        issues.append("approval_secret_exposed must be false")
    supplied = manifest.get("workers", [])
    by_name = {item.get("name"): item for item in supplied if isinstance(item, dict)}
    if set(by_name) != set(EXPECTED):
        issues.append(f"worker set mismatch: expected {sorted(EXPECTED)}, got {sorted(map(str, by_name))}")
    for name, (skills, tools) in EXPECTED.items():
        worker = by_name.get(name, {})
        if worker.get("ready") is not True:
            issues.append(f"{name} is not ready")
        if set(worker.get("skills", [])) != skills:
            issues.append(f"{name} skill assignment mismatch")
        if set(worker.get("tools", [])) != tools:
            issues.append(f"{name} tool boundary mismatch")
    if workers_snapshot is not None:
        actual = resource_names(workers_snapshot)
        missing = set(EXPECTED) - actual
        if missing:
            issues.append(f"AgentTeams worker CR snapshot is missing: {sorted(missing)}")
        binding_issues, observed_bindings = validate_worker_bindings(workers_snapshot)
        issues.extend(binding_issues)
    else:
        observed_bindings = {}
    if teams_snapshot is not None and "cyberguard-soc" not in resource_names(teams_snapshot):
        issues.append("AgentTeams team CR snapshot is missing cyberguard-soc")
    return {
        "valid": not issues,
        "team": "cyberguard-soc",
        "expected_workers": len(EXPECTED),
        "ready_workers": sum(by_name.get(name, {}).get("ready") is True for name in EXPECTED),
        "tool_services": sorted(manifest.get("tool_services", [])),
        "cr_snapshots_checked": workers_snapshot is not None and teams_snapshot is not None,
        "live_worker_bindings_checked": workers_snapshot is not None,
        "observed_worker_bindings": observed_bindings,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager-result", type=Path, required=True)
    parser.add_argument("--workers-json", type=Path)
    parser.add_argument("--teams-json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manager_result.read_text(encoding="utf-8"))
    workers = json.loads(args.workers_json.read_text(encoding="utf-8")) if args.workers_json else None
    teams = json.loads(args.teams_json.read_text(encoding="utf-8")) if args.teams_json else None
    result = validate(manifest, workers, teams)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
