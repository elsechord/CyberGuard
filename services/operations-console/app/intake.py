"""Bounded text intake. Producer claims remain unverified, inert source data.

Hashes identify submitted bytes and metadata; they establish neither authentic
origin nor factual correctness. Source URI labels are never dereferenced here.
"""
import hashlib
import json

MAX_SUBMISSION_BYTES = 1024 * 1024
MAX_CONTENT_BYTES = 128 * 1024
DOMAINS = frozenset({"security", "finance", "legal", "general"})
SOURCE_TYPES = frozenset({"agent", "firewall", "edr", "honeypot", "server_log",
                          "financial_record", "audit_report", "judicial_document", "other"})
MEDIA_TYPES = frozenset({"text/plain", "application/json", "text/markdown", "text/csv"})


def _canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Submission must contain valid UTF-8 JSON values") from exc


def _text(value, field, limit, *, required=True, byte_limit=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(field + " must be nonempty text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(field + " must be valid UTF-8 text") from exc
    if (len(encoded) if byte_limit else len(value)) > limit:
        raise ValueError(field + " exceeds its size limit")
    if any(ord(c) < 32 and c not in "\t\r\n" for c in value):
        raise ValueError(field + " contains unsupported binary/control data")
    return value


def _choice(value, choices, field):
    if not isinstance(value, str) or value not in choices:
        raise ValueError("Unsupported " + field)
    return value


def validate_submission(raw):
    """Return deterministic normalized intake without trusting caller identity.

    The HTTP layer must separately bound bytes before parsing JSON and reject
    duplicate JSON keys. This function also bounds programmatic submissions.
    Caller-supplied authentication, IDs, hashes and trust labels are rejected.
    """
    if not isinstance(raw, dict) or set(raw) != {"title", "objective", "domain", "materials"}:
        raise ValueError("Submission requires only title, objective, domain and materials")
    result = {
        "title": _text(raw["title"], "title", 200),
        "objective": _text(raw["objective"], "objective", 8000),
        "domain": _choice(raw["domain"], DOMAINS, "domain"),
        "materials": [],
    }
    materials = raw["materials"]
    if not isinstance(materials, list) or not 1 <= len(materials) <= 32:
        raise ValueError("materials must contain between 1 and 32 items")
    identities = set()
    required = {"source_type", "name", "content", "media_type"}
    optional = {"source_uri", "interpretation", "observed_at"}
    for material in materials:
        if not isinstance(material, dict) or not required <= set(material) or set(material) - required - optional:
            raise ValueError("Material has missing or unsupported fields")
        source = {
            "source_type": _choice(material["source_type"], SOURCE_TYPES, "source_type"),
            "name": _text(material["name"], "material name", 200),
            "content": _text(material["content"], "material content", MAX_CONTENT_BYTES, byte_limit=True),
            "media_type": _choice(material["media_type"], MEDIA_TYPES, "media_type"),
        }
        for key, limit in (("source_uri", 2048), ("observed_at", 128)):
            if key in material:
                source[key] = _text(material[key], key, limit, required=False)
        material_id = "MAT-" + hashlib.sha256(_canonical(source)).hexdigest()
        if material_id in identities:
            raise ValueError("Duplicate material identity")
        identities.add(material_id)
        normalized = dict(source)
        normalized.update({
            "material_id": material_id,
            "sha256": hashlib.sha256(source["content"].encode("utf-8")).hexdigest(),
            "source_authenticity": "unverified",
            "submitted_as": "original_input",
            "interpretation": _text(material.get("interpretation", ""), "interpretation",
                                    MAX_CONTENT_BYTES, required=False, byte_limit=True),
        })
        result["materials"].append(normalized)
    if len(_canonical(raw)) > MAX_SUBMISSION_BYTES or len(_canonical(result)) > MAX_SUBMISSION_BYTES:
        raise ValueError("Submission exceeds the 1 MiB aggregate size limit")
    result["request_fingerprint"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result
