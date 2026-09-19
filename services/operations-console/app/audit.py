"""Append-only authentication and decision audit trail (auth_event table).

Rows are never updated or deleted; the console audit page and the
/api/v1/audit-events endpoint are the only readers.
"""
import hashlib
import json
from datetime import UTC, datetime

from . import db


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record(event: str, *, actor: str | None = None, result: str | None = None,
           reason: str | None = None, ip: str | None = None,
           user_agent: str | None = None, target: str | None = None,
           session_id: str | None = None, request_id: str | None = None) -> None:
    session_hash = None
    if session_id:
        session_hash = hashlib.sha256(session_id.encode()).hexdigest()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO auth_event (ts, event, actor, result, reason, ip, user_agent, "
            "target, session_hash, request_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (now_iso(), event, actor, result, reason, ip, _clip(user_agent, 256),
             target, session_hash, request_id),
        )


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return value[:limit]


def list_events(*, before_id: int | None = None, limit: int = 20,
                event: str | None = None, actor: str | None = None) -> list[dict]:
    query = "SELECT * FROM auth_event"
    clauses, params = [], []
    if before_id is not None:
        clauses.append("id < ?")
        params.append(before_id)
    if event:
        clauses.append("event = ?")
        params.append(event)
    if actor:
        clauses.append("actor = ?")
        params.append(actor)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = db.connection().execute(query, params).fetchall()
    return [dict(row) for row in rows]


def recent_login_failures(username: str, window_seconds: int) -> tuple[int, str | None]:
    """Failures since the last successful login inside the lockout window."""
    from datetime import timedelta
    cutoff = (datetime.now(UTC) - timedelta(seconds=window_seconds)).isoformat()
    last_success = db.connection().execute(
        "SELECT MAX(ts) AS ts FROM auth_event "
        "WHERE event = 'login' AND actor = ? AND result = 'success'", (username,)
    ).fetchone()["ts"]
    rows = db.connection().execute(
        "SELECT ts FROM auth_event WHERE event = 'login' AND actor = ? "
        "AND result = 'failure' AND ts >= ? AND ts > COALESCE(?, '')",
        (username, cutoff, last_success),
    ).fetchall()
    timestamps = [row["ts"] for row in rows]
    return len(timestamps), max(timestamps) if timestamps else None


def decisions_for_action(action_id: str) -> list[dict]:
    rows = db.connection().execute(
        "SELECT * FROM decision WHERE action_id = ? ORDER BY id DESC", (action_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def record_decision(*, action_id: str, incident_id: str | None, actor: str,
                    action: str, classification: str, comment: str,
                    executor_status: int | None) -> int:
    with db.tx() as conn:
        cursor = conn.execute(
            "INSERT INTO decision (org_id, action_id, incident_id, actor, action, "
            "classification, comment, executor_status, created_at) "
            "VALUES ('default', ?,?,?,?,?,?,?,?)",
            (action_id, incident_id, actor, action, classification, comment,
             executor_status, now_iso()),
        )
        record("decision", actor=actor, result=action,
               reason=classification, target=action_id)
        return cursor.lastrowid


def export_events() -> list[dict]:
    rows = db.connection().execute("SELECT * FROM auth_event ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def dumps(record_value) -> str:
    return json.dumps(record_value, ensure_ascii=False, sort_keys=True)
