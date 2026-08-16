"""Vendor-neutral security observation normalization and quality scoring."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse


TOOL_PROFILE = {
    "alert.snapshot": ("findings", "security_finding"),
    "intel.lookup": ("discovery", "threat_intelligence"),
    "network.search": ("network_activity", "network_flow"),
    "boundary.policy": ("network_activity", "network_security_policy"),
    "endpoint.timeline": ("system_activity", "process_activity"),
    "asset.context": ("inventory", "asset_context"),
    "recovery.metrics": ("findings", "recovery_finding"),
}
ENTITY_KEYS = {
    "account": "user_account", "user": "user_account", "username": "user_account",
    "owner": "user_account", "deployment_actor": "user_account",
    "host": "device", "src_host": "device", "endpoint": "device",
    "workload": "workload", "src_workload": "workload", "pod": "workload",
    "service": "service", "namespace": "namespace", "image": "container_image",
    "firewall": "security_appliance", "gateway": "security_appliance",
    "firewall_cluster": "security_appliance", "zone": "network_zone",
}
OBSERVABLE_KEYS = {"indicator", "dst_domain", "domain", "url", "ip", "src_ip", "dst_ip", "dst_ips"}
DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z0-9-]{2,63}$")
ATTACK_ID = re.compile(r"^T\d{4}(?:\.\d{3})?$")


def _stable_id(prefix: str, kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{value.casefold()}".encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _walk(data: Any):
    if isinstance(data, dict):
        for key, value in data.items():
            yield str(key), value
            yield from _walk(value)
    elif isinstance(data, list):
        for value in data:
            yield from _walk(value)


def extract_entities(data: dict[str, Any]) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for key, value in _walk(data):
        entity_type = ENTITY_KEYS.get(key)
        values = value if isinstance(value, list) else [value]
        if entity_type:
            for item in values:
                if not isinstance(item, (str, int)) or not str(item).strip():
                    continue
                text = str(item).strip()
                entity_id = _stable_id("ENT", entity_type, text)
                found[entity_id] = {"entity_id": entity_id, "type": entity_type, "value": text}
        if key == "process_chain" and isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    entity_id = _stable_id("ENT", "process", item.strip())
                    found[entity_id] = {"entity_id": entity_id, "type": "process", "value": item.strip()}
    return [found[key] for key in sorted(found)]


def _observable(value: str, key: str) -> tuple[str, str] | None:
    text = value.strip()
    try:
        address = ipaddress.ip_address(text)
        return ("ipv4-addr" if address.version == 4 else "ipv6-addr", text)
    except ValueError:
        pass
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.hostname:
        return "url", text
    if DOMAIN.fullmatch(text):
        return "domain-name", text.lower()
    if key.endswith("hash") and re.fullmatch(r"[0-9a-fA-F]{32,128}", text):
        return "file-hash", text.lower()
    return None


def extract_observables(data: dict[str, Any]) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for key, value in _walk(data):
        if key not in OBSERVABLE_KEYS and not key.endswith("_hash"):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str):
                continue
            typed = _observable(item, key)
            if typed:
                stix_type, text = typed
                observable_id = _stable_id("OBS", stix_type, text)
                found[observable_id] = {
                    "observable_id": observable_id, "stix_type": stix_type, "value": text,
                }
    return [found[key] for key in sorted(found)]


def normalize(tool: str, record: dict[str, Any], raw_sha256: str) -> dict[str, Any]:
    source = str(record.get("source", "")).strip()
    kind = str(record.get("kind", tool)).strip()
    summary = str(record.get("summary", "")).strip()
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    confidence = record.get("confidence")
    required = [bool(source), bool(kind), bool(summary), isinstance(record.get("data"), dict),
                isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0 <= confidence <= 1]
    issues: list[str] = []
    observed_at = record.get("observed_at")
    timestamp_valid = False
    if observed_at:
        try:
            datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            timestamp_valid = True
        except ValueError:
            issues.append("invalid_observed_at")
    else:
        issues.append("missing_observed_at")
    entities = extract_entities(data)
    observables = extract_observables(data)
    techniques = sorted({str(item).upper() for item in record.get("attack_techniques", [])
                         if ATTACK_ID.fullmatch(str(item).upper())})
    invalid_techniques = len(record.get("attack_techniques", [])) - len(techniques)
    if invalid_techniques:
        issues.append("invalid_attack_technique_id")
    hypothesis_links = len(record.get("supports", [])) + len(record.get("contradicts", []))
    score = (0.5 * sum(required) / len(required) + 0.15 * timestamp_valid
             + 0.15 * bool(entities or observables) + 0.1 * bool(hypothesis_links)
             + 0.1 * bool(techniques))
    if not entities and not observables:
        issues.append("no_correlatable_entity_or_observable")
    if not hypothesis_links:
        issues.append("no_hypothesis_link")
    if not techniques:
        issues.append("no_attack_mapping")
    category, class_name = TOOL_PROFILE.get(tool, ("other", kind))
    return {
        "standard": {
            "schema": "cyberguard-security-observation", "version": "1.0",
            "alignment": {"event_profile": "OCSF-aligned", "cti_profile": "STIX-2.1"},
            "category_name": category, "class_name": class_name,
            "activity_name": tool, "raw_sha256": raw_sha256,
        },
        "entities": entities,
        "observables": observables,
        "attack_techniques": techniques,
        "quality": {
            "score": round(score, 3), "gate": "pass" if score >= 0.7 else "review",
            "issues": sorted(set(issues)), "required_fields_present": sum(required),
            "required_fields_total": len(required),
        },
    }
