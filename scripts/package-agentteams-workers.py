#!/usr/bin/env python3
"""Build deterministic AgentTeams Worker packages for the CyberGuard SOC team."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "agentteams-workers"
ROLE_SKILLS = {
    "alert-fusion": ["alert-triage", "hypothesis-testing"],
    "threat-intel": ["threat-intel-enrichment", "hypothesis-testing"],
    "network-hunter": ["network-hunting", "boundary-defense", "hypothesis-testing"],
    "endpoint-forensics": ["endpoint-forensics", "hypothesis-testing"],
    "response-planner": ["response-planning", "incident-reporting"],
    "controlled-responder": ["controlled-response"],
    "recovery-verifier": ["recovery-verification", "incident-reporting"],
}


def write_package(role: str, skills: list[str]) -> Path:
    target = OUTPUT / f"{role}.zip"
    manifest = {
        "version": "1.1.0",
        "source": {"project": "CyberGuard", "purpose": "GOAI Agent Infra security operations"},
        "worker": {"suggested_name": role, "runtime": "copaw", "skills": skills},
    }
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        for skill in skills:
            source = ROOT / "skills" / skill / "SKILL.md"
            if not source.is_file():
                raise FileNotFoundError(source)
            archive.write(source, f"skills/{skill}/SKILL.md")
    return target


def main() -> int:
    shutil.rmtree(OUTPUT, ignore_errors=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for role, skills in ROLE_SKILLS.items():
        print(write_package(role, skills))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
