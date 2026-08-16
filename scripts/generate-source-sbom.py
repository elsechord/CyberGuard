#!/usr/bin/env python3
"""Generate a deterministic SPDX 2.3 source/dependency SBOM."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s#]+)$")
FROM_RE = re.compile(r"^FROM\s+([^\s]+)", re.MULTILINE)


def spdx_id(name: str) -> str:
    return "SPDXRef-" + re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-")


def parse_release_date(version: str) -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^##\s+{re.escape(version)}\s+—\s+(\d{{4}}-\d{{2}}-\d{{2}})$", changelog, re.MULTILINE)
    if not match:
        raise ValueError(f"CHANGELOG.md lacks a release date for {version}")
    return match.group(1) + "T00:00:00Z"


def collect() -> tuple[str, list[dict[str, str]]]:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    components: dict[tuple[str, str, str], dict[str, str]] = {}
    for path in sorted((ROOT / "services").glob("*/requirements.txt")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = REQUIREMENT_RE.fullmatch(line)
            if not match:
                raise ValueError(f"unpinned Python requirement in {path}: {line}")
            name, component_version = match.groups()
            key = ("pypi", name.lower(), component_version)
            components[key] = {"kind": "pypi", "name": name, "version": component_version}
    lock_path = ROOT / "services" / "requirements.lock"
    for raw in lock_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--hash="):
            continue
        requirement = line.removesuffix("\\").strip()
        match = REQUIREMENT_RE.fullmatch(requirement)
        if not match:
            raise ValueError(f"invalid locked Python requirement in {lock_path}: {line}")
        name, component_version = match.groups()
        key = ("pypi", name.lower(), component_version)
        components[key] = {"kind": "pypi", "name": name, "version": component_version}
    for path in sorted((ROOT / "services").glob("*/Dockerfile")):
        matches = FROM_RE.findall(path.read_text(encoding="utf-8"))
        if len(matches) != 1 or "@sha256:" not in matches[0]:
            raise ValueError(f"{path} must use one digest-pinned base image")
        image, digest = matches[0].split("@sha256:", 1)
        slash = image.rfind("/")
        colon = image.rfind(":")
        if colon > slash:
            repository, tag = image[:colon], image[colon + 1:]
        else:
            repository, tag = image, "latest"
        key = ("docker", image, digest)
        components[key] = {
            "kind": "docker", "name": image, "version": f"sha256:{digest}",
            "repository": repository, "tag": tag,
        }
    components[("github", "agentscope-ai/AgentTeams", "v1.2.2")] = {
        "kind": "github", "name": "agentscope-ai/AgentTeams", "version": "v1.2.2"
    }
    return version, [components[key] for key in sorted(components)]


def build_document() -> dict[str, object]:
    version, components = collect()
    fingerprint = hashlib.sha256(json.dumps(components, sort_keys=True).encode()).hexdigest()
    project_id = "SPDXRef-Package-CyberGuard"
    packages: list[dict[str, object]] = [{
        "SPDXID": project_id, "name": "CyberGuard", "versionInfo": version,
        "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
        "licenseConcluded": "Apache-2.0", "licenseDeclared": "Apache-2.0",
        "copyrightText": "NOASSERTION",
        "supplier": "Organization: Hangzhou Dianzi University System Security Laboratory",
    }]
    relationships: list[dict[str, str]] = [{
        "spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES",
        "relatedSpdxElement": project_id,
    }]
    for component in components:
        component_id = spdx_id(f"Package-{component['kind']}-{component['name']}-{component['version']}")
        if component["kind"] == "pypi":
            purl = f"pkg:pypi/{component['name'].lower()}@{component['version']}"
        elif component["kind"] == "docker":
            purl = f"pkg:docker/{component['repository']}@{component['version']}?tag={component['tag']}"
        else:
            purl = f"pkg:github/{component['name']}@{component['version']}"
        packages.append({
            "SPDXID": component_id, "name": component["name"], "versionInfo": component["version"],
            "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION", "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "externalRefs": [{
                "referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                "referenceLocator": purl,
            }],
        })
        relationships.append({
            "spdxElementId": project_id, "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": component_id,
        })
    return {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"CyberGuard-{version}-source",
        "documentNamespace": f"https://cyberguard.invalid/spdx/{version}/{fingerprint}",
        "creationInfo": {
            "created": parse_release_date(version),
            "creators": ["Tool: CyberGuard-generate-source-sbom", "Organization: Hangzhou Dianzi University System Security Laboratory"],
        },
        "packages": packages, "relationships": relationships,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = build_document()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote deterministic SPDX SBOM: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
