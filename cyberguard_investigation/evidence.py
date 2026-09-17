"""Bounded, dependency-free evidence envelope and strict JSON import."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SCHEMA = "cyberguard-evidence-bundle/v1"
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024
MAX_ARTIFACTS = 2048


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _bounded_json(value):
    remaining = 100000
    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 32:
            raise ValueError("JSON structure exceeds limits")
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, str):
            if len(item) > MAX_ARTIFACT_BYTES:
                raise ValueError("JSON string exceeds limit")
            return
        if isinstance(item, (int, float)):
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Non-finite JSON number")
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 4096:
                    raise ValueError("Invalid JSON key")
                visit(child, depth + 1)
            return
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        raise ValueError("Unsupported JSON value")
    visit(value, 0)


def canonical_bytes(value):
    _bounded_json(value)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("Invalid canonical JSON") from exc


def _digest(value, field):
    return hashlib.sha256(canonical_bytes({k: v for k, v in value.items() if k != field})).hexdigest()


def _text(value, name, maximum=4096):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError("Invalid " + name)


def _timestamp(value):
    _text(value, "timestamp", 64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Missing timezone")
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc


def make_artifact(kind, source, data, *, status="collected", observed_at=None, collected_at=None):
    collected_at = collected_at or utc_now()
    artifact = {"evidence_id": "EV-" + uuid4().hex, "kind": kind, "source": source,
                "collected_at": collected_at, "observed_at": observed_at or collected_at,
                "status": status, "data": data}
    artifact["sha256"] = _digest(artifact, "sha256")
    _validate_artifact(artifact)
    return artifact


def _validate_artifact(artifact):
    fields = {"evidence_id", "kind", "source", "collected_at", "observed_at", "status", "data", "sha256"}
    if not isinstance(artifact, dict) or set(artifact) != fields:
        raise ValueError("Invalid artifact fields")
    for key in ("evidence_id", "kind"):
        _text(artifact[key], key, 128)
    _text(artifact["source"], "source")
    _timestamp(artifact["collected_at"])
    _timestamp(artifact["observed_at"])
    if artifact["status"] not in ("collected", "unavailable") or not isinstance(artifact["data"], dict):
        raise ValueError("Invalid artifact status or data")
    if len(canonical_bytes(artifact)) > MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact exceeds byte limit")
    if not isinstance(artifact["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
        raise ValueError("Invalid artifact SHA256")
    if artifact["sha256"] != _digest(artifact, "sha256"):
        raise ValueError("Artifact SHA256 mismatch")


def make_bundle(artifacts, *, provenance, bundle_id=None):
    bundle = {"schema": SCHEMA, "bundle_id": bundle_id or "BUNDLE-" + uuid4().hex,
              "created_at": utc_now(), "provenance": provenance, "artifacts": list(artifacts)}
    bundle["bundle_sha256"] = _digest(bundle, "bundle_sha256")
    return validate_bundle(bundle)


def validate_bundle(bundle):
    """Return validated object; integrity is NOT authentication or factual correctness."""
    fields = {"schema", "bundle_id", "created_at", "provenance", "artifacts", "bundle_sha256"}
    if not isinstance(bundle, dict) or set(bundle) != fields or bundle["schema"] != SCHEMA:
        raise ValueError("Unsupported bundle envelope")
    _text(bundle["bundle_id"], "bundle_id", 128)
    _timestamp(bundle["created_at"])
    provenance = bundle["provenance"]
    if not isinstance(provenance, dict) or provenance.get("kind") not in ("live_collection", "exercise", "import"):
        raise ValueError("Invalid provenance")
    artifacts = bundle["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) > MAX_ARTIFACTS:
        raise ValueError("Artifact count exceeds limit")
    if len(canonical_bytes(bundle)) > MAX_BUNDLE_BYTES:
        raise ValueError("Bundle exceeds byte limit")
    identities = set()
    for artifact in artifacts:
        _validate_artifact(artifact)
        if artifact["evidence_id"] in identities:
            raise ValueError("Duplicate evidence_id")
        identities.add(artifact["evidence_id"])
    if bundle["bundle_sha256"] != _digest(bundle, "bundle_sha256"):
        raise ValueError("Bundle SHA256 mismatch")
    return bundle


def load_bundle(path):
    """Bounded import. Keep producer provenance intact; do not upgrade its trust."""
    with Path(path).open("rb") as stream:
        payload = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(payload) > MAX_BUNDLE_BYTES:
        raise ValueError("Bundle exceeds byte limit")
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    try:
        bundle = json.loads(payload.decode("utf-8"), object_pairs_hook=object_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite number")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid bundle JSON") from exc
    return validate_bundle(bundle)
