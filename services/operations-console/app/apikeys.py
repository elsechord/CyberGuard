"""API keys: cg_live_ tokens, sha256-at-rest, scope-tagged, revocable.

The complete plaintext key is returned exactly once at creation time; only
sha256(key) plus a 14-character display prefix is persisted.
"""
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

from . import audit, config, db


def generate_key() -> str:
    return config.KEY_PREFIX + secrets.token_urlsafe(32)


def key_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_key(*, name: str, scopes: list[str], created_by: str,
               expires_at: str | None = None) -> tuple[int, str, dict]:
    unknown = [scope for scope in scopes if scope not in auth_all_scopes()]
    if unknown or not scopes:
        raise ValueError("invalid scopes")
    raw = generate_key()
    prefix = raw[:14]
    row = {
        "name": name,
        "prefix": prefix,
        "scopes": sorted(set(scopes)),
        "created_by": created_by,
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": expires_at,
        "revoked_at": None,
        "last_used_at": None,
    }
    with db.tx() as conn:
        cursor = conn.execute(
            "INSERT INTO api_key (org_id, name, prefix, key_hash, scopes, created_by, "
            "created_at, expires_at) VALUES ('default',?,?,?,?,?,?,?)",
            (name, prefix, key_hash(raw), json.dumps(row["scopes"]),
             created_by, row["created_at"], expires_at),
        )
        row["id"] = cursor.lastrowid
        audit.record("api_key_created", actor=created_by, target=prefix)
    return row["id"], raw, row


def auth_all_scopes() -> list[str]:
    from .auth import ALL_SCOPES
    return ALL_SCOPES


def verify_key(raw: str):
    """Valid, unexpired, unrevoked key row or None. Touches last_used_at."""
    if not raw.startswith(config.KEY_PREFIX):
        return None
    digest = key_hash(raw)
    row = db.connection().execute(
        "SELECT * FROM api_key WHERE key_hash = ?", (digest,)
    ).fetchone()
    if row is None:
        return None
    if row["revoked_at"]:
        return None
    if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        return None
    now = datetime.now(UTC).isoformat()
    if not row["last_used_at"] or _older_than(row["last_used_at"], 60):
        with db.tx() as conn:
            conn.execute("UPDATE api_key SET last_used_at = ? WHERE id = ?",
                         (now, row["id"]))
    return row


def _older_than(stored: str, seconds: int) -> bool:
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(stored)) > timedelta(seconds=seconds)
    except ValueError:
        return True


def revoke_key(key_id: int, actor: str) -> bool:
    with db.tx() as conn:
        cursor = conn.execute(
            "UPDATE api_key SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (datetime.now(UTC).isoformat(), key_id),
        )
        revoked = cursor.rowcount > 0
    if revoked:
        audit.record("api_key_revoked", actor=actor, target=str(key_id))
    return revoked


def list_keys() -> list[dict]:
    rows = db.connection().execute(
        "SELECT id, name, prefix, scopes, created_by, created_at, last_used_at, "
        "expires_at, revoked_at FROM api_key ORDER BY id DESC"
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["scopes"] = json.loads(item["scopes"])
        except (TypeError, ValueError):
            item["scopes"] = []
        result.append(item)
    return result


def expiry_from_days(days: int | None) -> str | None:
    if days is None or days <= 0:
        return None
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()
