"""Idempotency-Key support for mutating API v1 endpoints.

Keys are scoped to (principal, endpoint); entries live 24 hours. A replay with
identical parameters returns the stored response; a replay with different
parameters raises idempotency_error.
"""
import hashlib
import json
from datetime import UTC, datetime, timedelta

from . import config, db


def request_fingerprint(payload) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def lookup(key: str, scope: str):
    row = db.connection().execute(
        "SELECT * FROM idempotency WHERE key = ? AND scope = ?", (key, scope)
    ).fetchone()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        with db.tx() as conn:
            conn.execute("DELETE FROM idempotency WHERE key = ? AND scope = ?",
                         (key, scope))
        return None
    return row


def store(key: str, scope: str, request_hash: str, status: int, body: str) -> None:
    now = datetime.now(UTC)
    with db.tx() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO idempotency "
            "(key, scope, request_hash, status, body, created_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (key, scope, request_hash, status, body, now.isoformat(),
             (now + timedelta(seconds=config.IDEMPOTENCY_TTL_SECONDS)).isoformat()),
        )


def purge_expired() -> None:
    with db.tx() as conn:
        conn.execute("DELETE FROM idempotency WHERE expires_at <= ?",
                     (datetime.now(UTC).isoformat(),))
