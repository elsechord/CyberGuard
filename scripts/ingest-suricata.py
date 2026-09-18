"""Read-only Suricata EVE JSON ingest adapter for the CyberGuard evidence store.

Converts alert events from Suricata EVE JSON line output into Evidence 1.0
records using the gateway normalization module (stable entity/observable IDs,
STIX typing, ATT&CK validation, quality scoring), validates each record
against contracts/evidence.schema.json and appends to evidence.jsonl.

Design rules:
* Read-only adapter: never rewrites or mutates existing evidence lines; append only.
* ATT&CK mapping is conservative keyword-based inference; when no mapping can be
  defended the technique list stays empty and normalization records the
  ``no_attack_mapping`` issue. Techniques are never invented.
* Severity maps to confidence as 1->0.9, 2->0.75, 3->0.6, unknown->0.5.
* Raw-record sha256 is computed over the canonical original EVE event, so
  re-running the adapter is idempotent (already-present shas are skipped).
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "security-tool-gateway"))

SOURCE = "network-sensor/suricata"
SEVERITY_CONFIDENCE = {1: 0.9, 2: 0.75, 3: 0.6}
FLOW_CONFIDENCE = 0.75
# Conservative signature/category keyword -> ATT&CK technique hints. Each entry
# is a direct semantic match on the signature text; anything not listed here
# stays unmapped (quality issue recorded, nothing invented).
ATTACK_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("port scan", "portscan", "nmap", "ssh scan", "scan for ssh"), "T1046"),
    (("brute force", "password guess", "multiple failed log", "login brute"), "T1110"),
    (("sql injection",), "T1190"),
    (("dns tunnel", "dnscat", "iodine", "dns2tcp"), "T1071.004"),
    (("web shell", "webshell"), "T1505.003"),
    (("phishing", "phish"), "T1566"),
)
_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")


def _canonical_digest(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def eve_timestamp(value: Any) -> str | None:
    """Normalize the EVE timestamp (e.g. ...+0000) to strict RFC 3339."""
    if value is None:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).isoformat()
            except ValueError:
                continue
    return None


def map_attack_techniques(*text_parts: Any) -> list[str]:
    haystack = " ".join(str(part) for part in text_parts if part).lower()
    if not haystack:
        return []
    matched = {technique for keywords, technique in ATTACK_HINTS
               if any(keyword in haystack for keyword in keywords)}
    return sorted(matched)


def _protocol_context(event: dict[str, Any]) -> dict[str, Any]:
    """Extract honest, spec-named observables from embedded app-layer records."""
    context: dict[str, Any] = {}
    http = event.get("http")
    if isinstance(http, dict):
        hostname = http.get("hostname")
        if isinstance(hostname, str) and hostname.strip():
            context["dst_domain"] = hostname.strip()
            url = http.get("url")
            if isinstance(url, str) and url.strip():
                scheme = "https" if event.get("dest_port") == 443 else "http"
                context["url"] = f"{scheme}://{hostname.strip()}{url.strip()}"
        if isinstance(http.get("http_method"), str):
            context["http_method"] = http["http_method"]
    dns = event.get("dns")
    if isinstance(dns, dict):
        names: list[str] = []
        if isinstance(dns.get("rrname"), str):
            names.append(dns["rrname"])
        for section in ("queries", "answers", "authorities", "additionals"):
            for item in dns.get(section) or []:
                if isinstance(item, dict) and isinstance(item.get("rrname"), str):
                    names.append(item["rrname"])
        if names:
            context["domain"] = sorted(set(n.strip() for n in names if n.strip()))[0]
            context["dns_type"] = dns.get("type", "")
    tls = event.get("tls")
    if isinstance(tls, dict):
        sni = tls.get("sni")
        if isinstance(sni, str) and sni.strip() and "dst_domain" not in context:
            context["dst_domain"] = sni.strip()
        if isinstance(tls.get("version"), str):
            context["tls_version"] = tls["version"]
    return context


def alert_record(event: dict[str, Any], sensor: str) -> dict[str, Any] | None:
    alert = event.get("alert")
    if not isinstance(alert, dict) or not str(alert.get("signature", "")).strip():
        return None
    signature = str(alert["signature"]).strip()
    severity = alert.get("severity")
    confidence = (SEVERITY_CONFIDENCE.get(severity, 0.5) if isinstance(severity, int)
                  and not isinstance(severity, bool) else 0.5)
    data: dict[str, Any] = {"host": sensor, "signature_id": alert.get("signature_id"),
                            "signature": signature, "alert_category": alert.get("category"),
                            "severity": severity, "alert_action": alert.get("action")}
    for key in ("flow_id", "src_ip", "dest_ip", "src_port", "dest_port", "proto", "app_proto"):
        if event.get(key) is not None:
            data[key if key != "dest_ip" else "dst_ip"] = event[key]
    data.update(_protocol_context(event))
    src, dst = event.get("src_ip"), event.get("dest_ip")
    summary = f"Suricata alert: {signature}"
    if src and dst:
        summary += f" ({src} -> {dst})"
    return {"source": SOURCE, "kind": "network_alert", "observed_at": eve_timestamp(event.get("timestamp")),
            "summary": summary, "confidence": confidence,
            "attack_techniques": map_attack_techniques(signature, alert.get("category")), "data": data}


def flow_record(event: dict[str, Any], sensor: str) -> dict[str, Any] | None:
    if not event.get("src_ip") or not event.get("dest_ip"):
        return None
    flow = event.get("flow") if isinstance(event.get("flow"), dict) else {}
    data: dict[str, Any] = {"host": sensor, "flow_id": event.get("flow_id"),
                            "src_ip": event.get("src_ip"), "dst_ip": event.get("dest_ip"),
                            "src_port": event.get("src_port"), "dst_port": event.get("dest_port"),
                            "proto": event.get("proto"), "app_proto": event.get("app_proto")}
    for key in ("pkts_toserver", "pkts_toclient", "bytes_toserver", "bytes_toclient", "state"):
        if flow.get(key) is not None:
            data[key] = flow[key]
    return {"source": SOURCE, "kind": "network_flow", "observed_at": eve_timestamp(event.get("timestamp")),
            "summary": (f"Suricata flow {event.get('src_ip')} -> {event.get('dest_ip')}"
                        f" proto {event.get('proto')} state {flow.get('state', 'unknown')}"),
            "confidence": FLOW_CONFIDENCE, "attack_techniques": [], "data": data}


def build_evidence(record: dict[str, Any], incident_id: str, digest: str,
                   environment: str, execution: str) -> Any:
    from app.models import Evidence
    from app.normalization import normalize

    normalized = normalize("suricata.eve", record, digest)
    evidence = Evidence(
        evidence_id=f"EV-{uuid4().hex[:12]}", incident_id=incident_id, environment=environment,
        execution=execution, source=record["source"], collected_at=datetime.now(UTC).isoformat(),
        observed_at=record.get("observed_at"), kind=record["kind"], summary=record["summary"],
        data=record["data"], sha256=digest, confidence=float(record["confidence"]),
        handling="internal", **normalized,
    )
    envelope = evidence.model_dump(exclude={"envelope_sha256"})
    evidence.envelope_sha256 = hashlib.sha256(json.dumps(
        envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    return evidence


# Minimal fail-closed JSON Schema validator covering exactly the keyword set
# used by contracts/evidence.schema.json; unknown keywords are an error.
_ANNOTATIONS = {"$schema", "$id", "title", "description"}
# Gateway transport envelope fields persisted alongside the Evidence 1.0
# contract object in evidence.jsonl (see services/.../app/models.py::Evidence);
# they are validated by the pydantic model, not by contracts/evidence.schema.json.
ENVELOPE_FIELDS = frozenset({"run_id", "scenario_id", "tool_call_id",
                             "environment", "execution", "envelope_sha256"})
_TYPE_MAP = {"object": dict, "array": list, "string": str, "boolean": bool,
             "null": type(None)}


def validate_contract(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    for keyword, constraint in schema.items():
        if keyword in _ANNOTATIONS:
            continue
        if keyword == "type":
            types = constraint if isinstance(constraint, list) else [constraint]
            ok = False
            for expected in types:
                if expected == "number" and isinstance(instance, (int, float)) and not isinstance(instance, bool):
                    ok = True
                elif expected == "integer" and isinstance(instance, int) and not isinstance(instance, bool):
                    ok = True
                elif expected in _TYPE_MAP and isinstance(instance, _TYPE_MAP[expected]) and (
                        expected == "boolean" or not isinstance(instance, bool)):
                    ok = True
            if not ok:
                errors.append(f"{path}: expected type {constraint}, got {type(instance).__name__}")
        elif keyword == "required":
            if isinstance(instance, dict):
                errors += [f"{path}: missing required property {name!r}"
                           for name in constraint if name not in instance]
        elif keyword == "properties":
            if isinstance(instance, dict):
                for name, sub in constraint.items():
                    if name in instance:
                        errors += validate_contract(instance[name], sub, f"{path}.{name}")
        elif keyword == "additionalProperties":
            if isinstance(instance, dict) and constraint is False:
                allowed = set(schema.get("properties", {}))
                errors += [f"{path}: unexpected property {name!r}"
                           for name in instance if name not in allowed]
        elif keyword == "items":
            if isinstance(instance, list):
                for index, item in enumerate(instance):
                    errors += validate_contract(item, constraint, f"{path}[{index}]")
        elif keyword == "pattern":
            if isinstance(instance, str) and not re.search(constraint, instance):
                errors.append(f"{path}: {instance!r} does not match pattern {constraint!r}")
        elif keyword in {"enum", "const"}:
            allowed = constraint if keyword == "enum" else [constraint]
            if not any(type(instance) is type(option) and instance == option for option in allowed):
                errors.append(f"{path}: {instance!r} not in {constraint!r}")
        elif keyword in {"minimum", "maximum"}:
            if isinstance(instance, (int, float)) and not isinstance(instance, bool):
                if keyword == "minimum" and instance < constraint:
                    errors.append(f"{path}: {instance} < minimum {constraint}")
                if keyword == "maximum" and instance > constraint:
                    errors.append(f"{path}: {instance} > maximum {constraint}")
        elif keyword == "format" and constraint == "date-time":
            if isinstance(instance, str):
                try:
                    datetime.fromisoformat(instance.replace("Z", "+00:00"))
                except ValueError:
                    errors.append(f"{path}: {instance!r} is not a date-time")
        else:
            errors.append(f"{path}: unsupported schema keyword {keyword!r}")
    return errors


def iter_input_files(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            files += sorted(p for p in item.iterdir() if p.suffix in {".json", ".jsonl"})
        elif item.is_file():
            files.append(item)
        else:
            raise FileNotFoundError(str(item))
    return list(dict.fromkeys(files))


def existing_sha256(data_dir: Path) -> set[str]:
    path = data_dir / "evidence.jsonl"
    if not path.exists():
        return set()
    shas: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            try:
                shas.add(json.loads(line).get("sha256"))
            except json.JSONDecodeError:
                continue
    return shas


def write_workflow(data_dir: Path, incident_id: str) -> str:
    os.environ["CYBERGUARD_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("CYBERGUARD_ACTION_AUDIT_FILE", str(data_dir / "actions.jsonl"))
    from app.store import ScenarioStore

    store = ScenarioStore()
    session_id, actor = "ingest-suricata", "suricata-ingest"
    current = store.workflow(incident_id, session_id)
    if current is None:
        store.transition_workflow(incident_id, session_id, "received", actor=actor,
                                   message="Suricata EVE alerts ingested")
        store.transition_workflow(incident_id, session_id, "investigating", actor=actor,
                                  message="Operator review of ingested sensor alerts")
        return "written"
    if current["state"] == "received":
        store.transition_workflow(incident_id, session_id, "investigating", actor=actor,
                                  message="Operator review of ingested sensor alerts")
        return "written"
    return "already_present"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True,
                        help="EVE JSON file(s) or directory containing *.json/*.jsonl")
    parser.add_argument("--incident", required=True, help="incident id, e.g. CG-SURICATA-001")
    parser.add_argument("--data-dir", type=Path, required=True,
                        help="gateway data dir holding evidence.jsonl (append only)")
    parser.add_argument("--dry-run", action="store_true", help="validate and report without writing")
    parser.add_argument("--include-flows", action="store_true",
                        help="also convert flow summary events (default: alerts only)")
    parser.add_argument("--workflow", action="store_true",
                        help="record an investigating workflow event for the incident")
    parser.add_argument("--sensor", default="suricata-sensor",
                        help="sensor name recorded as the reporting device entity")
    parser.add_argument("--environment", choices=("live", "fixture"), default="live",
                        help="live = real sensor export; fixture = spec-sample data")
    args = parser.parse_args(argv)

    incident_id = args.incident.strip()
    if not incident_id or len(incident_id) > 128 or Path(incident_id).name != incident_id:
        parser.error("--incident must be a plain identifier without path separators")

    try:
        schema = json.loads((ROOT / "contracts" / "evidence.schema.json").read_text(encoding="utf-8"))
        files = iter_input_files(args.input)
        known_shas = existing_sha256(args.data_dir)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}), file=sys.stderr)
        return 1

    execution = "real" if args.environment == "live" else "simulated"
    stats = {"files": len(files), "read": 0, "converted": 0, "appended": 0,
             "skipped": {"non_alert": 0, "stats": 0, "flow_excluded": 0,
                         "invalid": 0, "duplicate": 0},
             "quality": {"pass": 0, "review": 0, "scores": []},
             "entities": set(), "observables": set(), "attack_techniques": set()}
    lines_out: list[str] = []
    for file in files:
        for line in file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            stats["read"] += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                stats["skipped"]["invalid"] += 1
                continue
            if not isinstance(event, dict) or not isinstance(event.get("event_type"), str):
                stats["skipped"]["invalid"] += 1
                continue
            event_type = event["event_type"].lower()
            if event_type == "stats":
                stats["skipped"]["stats"] += 1
                continue
            if event_type == "alert":
                record = alert_record(event, args.sensor)
                if record is None:
                    stats["skipped"]["invalid"] += 1
                    continue
            elif event_type == "flow" and args.include_flows:
                record = flow_record(event, args.sensor)
                if record is None:
                    stats["skipped"]["invalid"] += 1
                    continue
            elif event_type == "flow":
                stats["skipped"]["flow_excluded"] += 1
                continue
            else:
                stats["skipped"]["non_alert"] += 1
                continue
            stats["converted"] += 1
            digest = _canonical_digest(event)
            if digest in known_shas:
                stats["skipped"]["duplicate"] += 1
                continue
            evidence = build_evidence(record, incident_id, digest, args.environment, execution)
            envelope = evidence.model_dump()
            contract_object = {key: value for key, value in envelope.items()
                               if key not in ENVELOPE_FIELDS}
            errors = validate_contract(contract_object, schema)
            if errors:
                print(json.dumps({"status": "failed",
                                  "reason": "converted record violates evidence contract",
                                  "errors": errors}), file=sys.stderr)
                return 1
            known_shas.add(digest)
            stats["quality"]["pass" if envelope["quality"]["gate"] == "pass" else "review"] += 1
            stats["quality"]["scores"].append(envelope["quality"]["score"])
            stats["entities"] |= {entity["entity_id"] for entity in envelope["entities"]}
            stats["observables"] |= {item["observable_id"] for item in envelope["observables"]}
            stats["attack_techniques"] |= set(envelope["attack_techniques"])
            stats["appended"] += 1
            lines_out.append(evidence.model_dump_json())

    if lines_out and not args.dry_run:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        with (args.data_dir / "evidence.jsonl").open("a", encoding="utf-8") as stream:
            stream.writelines(line + "\n" for line in lines_out)

    workflow = "skipped"
    if args.workflow and not args.dry_run:
        workflow = write_workflow(args.data_dir, incident_id)

    scores = stats["quality"]["scores"]
    summary = {
        "status": "ok" if not args.dry_run else "ok_dry_run",
        "incident_id": incident_id, "input_files": stats["files"], "events_read": stats["read"],
        "converted": stats["converted"], "appended": stats["appended"] if not args.dry_run else 0,
        "skipped": stats["skipped"],
        "quality": {
            "pass": stats["quality"]["pass"], "review": stats["quality"]["review"],
            "min": min(scores) if scores else None, "max": max(scores) if scores else None,
            "mean": round(sum(scores) / len(scores), 3) if scores else None,
        },
        "entity_count": len(stats["entities"]), "observable_count": len(stats["observables"]),
        "attack_techniques_mapped": sorted(stats["attack_techniques"]),
        "workflow": workflow,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
