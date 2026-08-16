#!/usr/bin/env python3
"""Validate deploy-time configuration without printing secret values."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


PINNED_AGENTTEAMS = {
    "AGENTTEAMS_VERSION": "v1.2.2",
    "AGENTTEAMS_INSTALL_COMMIT": "849182af8e017168a5a200a87b1062142caf462d",
    "AGENTTEAMS_INSTALL_SHA256": "8ef28c5bf239a0af2d6b57b946ecee977bf39e6c874cd786b85c7bd094668f9d",
}
PLACEHOLDER_RE = re.compile(r"replace(?:-with)?|changeme|example|your[-_]", re.IGNORECASE)
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ConfigError(ValueError):
    pass


def parse_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ConfigError(f"missing configuration file: {path}")
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not KEY_RE.fullmatch(key):
            raise ConfigError(f"{path}:{line_number}: invalid variable name {key!r}")
        if key in values:
            raise ConfigError(f"{path}:{line_number}: duplicate variable {key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def require(values: dict[str, str], key: str) -> str:
    value = values.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} is required")
    if PLACEHOLDER_RE.search(value):
        raise ConfigError(f"{key} still contains a placeholder")
    return value


def validate_url(values: dict[str, str], key: str, allow_http: bool) -> None:
    value = values.get(key, "").strip()
    if not value:
        return
    parsed = urlparse(value)
    allowed = {"https"} | ({"http"} if allow_http else set())
    if parsed.scheme not in allowed or not parsed.netloc or parsed.username or parsed.password:
        suffix = "HTTPS" if not allow_http else "HTTP(S)"
        raise ConfigError(f"{key} must be a credential-free absolute {suffix} URL")


def validate_cyberguard(values: dict[str, str]) -> dict[str, object]:
    secret_keys = (
        "CYBERGUARD_API_TOKEN",
        "CYBERGUARD_EXECUTOR_TOKEN",
        "CYBERGUARD_APPROVAL_SECRET",
        "CYBERGUARD_AUDIT_HMAC_KEY",
        "CYBERGUARD_AUDIT_READER_TOKEN",
    )
    secrets = [require(values, key) for key in secret_keys]
    for key, value in zip(secret_keys, secrets):
        if len(value) < 32:
            raise ConfigError(f"{key} must contain at least 32 characters")
    if len(set(secrets)) != len(secrets):
        raise ConfigError("CyberGuard service, approval and audit secrets must be distinct")

    allow_raw = values.get("CYBERGUARD_ALLOW_INSECURE_HTTP", "0")
    if allow_raw not in {"0", "1"}:
        raise ConfigError("CYBERGUARD_ALLOW_INSECURE_HTTP must be 0 or 1")
    allow_http = allow_raw == "1"
    try:
        minimum_quality = float(values.get("CYBERGUARD_MIN_EVIDENCE_QUALITY", "0.7"))
    except ValueError as exc:
        raise ConfigError("CYBERGUARD_MIN_EVIDENCE_QUALITY must be a number from 0 to 1") from exc
    if not 0 <= minimum_quality <= 1:
        raise ConfigError("CYBERGUARD_MIN_EVIDENCE_QUALITY must be a number from 0 to 1")
    url_keys = (
        "CYBERGUARD_SIEM_BASE_URL", "CYBERGUARD_NDR_BASE_URL",
        "CYBERGUARD_FIREWALL_BASE_URL", "CYBERGUARD_EDR_BASE_URL",
        "CYBERGUARD_CMDB_BASE_URL", "CYBERGUARD_MISP_URL",
    )
    for key in url_keys:
        validate_url(values, key, allow_http)
    return {
        "profile": "cyberguard",
        "secret_count": len(secrets),
        "configured_url_count": sum(bool(values.get(key, "").strip()) for key in url_keys),
        "insecure_http": allow_http,
        "minimum_evidence_quality": minimum_quality,
    }


def validate_agentteams(values: dict[str, str], expected_root: Path) -> dict[str, object]:
    for key, expected in PINNED_AGENTTEAMS.items():
        if require(values, key) != expected:
            raise ConfigError(f"{key} must match the validated AgentTeams v1.2.2 pin")

    if len(require(values, "AGENTTEAMS_LLM_API_KEY")) < 8:
        raise ConfigError("AGENTTEAMS_LLM_API_KEY is implausibly short")
    require(values, "AGENTTEAMS_DEFAULT_MODEL")
    if len(require(values, "AGENTTEAMS_ADMIN_PASSWORD")) < 12:
        raise ConfigError("AGENTTEAMS_ADMIN_PASSWORD must contain at least 12 characters")
    if values.get("AGENTTEAMS_LOCAL_ONLY", "") != "1":
        raise ConfigError("AGENTTEAMS_LOCAL_ONLY must remain 1 on the competition server")
    if values.get("AGENTTEAMS_MATRIX_E2EE", "") != "0":
        raise ConfigError("AGENTTEAMS_MATRIX_E2EE must remain 0 for the pinned automation workflow")

    expected_paths = {
        "AGENTTEAMS_WORKSPACE_DIR": expected_root / "agentteams-manager",
        "AGENTTEAMS_HOST_SHARE_DIR": expected_root / "host-share",
    }
    for key, expected in expected_paths.items():
        if Path(require(values, key)) != expected:
            raise ConfigError(f"{key} must be {expected}")
    return {
        "profile": "agentteams", "version": values["AGENTTEAMS_VERSION"],
        "local_only": True, "matrix_e2ee": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cyberguard-env", type=Path)
    parser.add_argument("--agentteams-env", type=Path)
    parser.add_argument("--expected-root", type=Path, default=Path("/srv/cyberguard"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.cyberguard_env and not args.agentteams_env:
        parser.error("provide at least one configuration file")
    results: list[dict[str, object]] = []
    try:
        if args.cyberguard_env:
            results.append(validate_cyberguard(parse_env(args.cyberguard_env)))
        if args.agentteams_env:
            results.append(validate_agentteams(parse_env(args.agentteams_env), args.expected_root))
    except (ConfigError, OSError, UnicodeError) as exc:
        print(f"Configuration invalid: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"valid": True, "profiles": results}, sort_keys=True))
    else:
        print("Configuration validation passed: " + ", ".join(str(x["profile"]) for x in results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
