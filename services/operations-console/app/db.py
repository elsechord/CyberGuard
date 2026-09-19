"""SQLite persistence: one file, WAL mode, idempotent schema creation.

Connections are per-thread (FastAPI runs sync endpoints in a worker thread
pool) and every connection applies the same PRAGMA contract:
busy_timeout=5000, synchronous=NORMAL, foreign_keys=ON.
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import config

_LOCAL = threading.local()
SCHEMA = """
CREATE TABLE IF NOT EXISTS organization (
    id TEXT PRIMARY KEY DEFAULT 'default',
    setup_token TEXT,
    setup_used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS "user" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL DEFAULT 'default' REFERENCES organization(id),
    username TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer','analyst','approver','admin')),
    created_at TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    UNIQUE (org_id, username)
);
CREATE TABLE IF NOT EXISTS session (
    sid_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_key (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    scopes TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    expires_at TEXT,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS auth_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    actor TEXT,
    result TEXT,
    reason TEXT,
    ip TEXT,
    user_agent TEXT,
    target TEXT,
    session_hash TEXT,
    request_id TEXT
);
CREATE TABLE IF NOT EXISTS decision (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL DEFAULT 'default',
    action_id TEXT NOT NULL,
    incident_id TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    classification TEXT NOT NULL,
    comment TEXT NOT NULL,
    executor_status INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL DEFAULT 'default',
    incident_id TEXT NOT NULL,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT NOT NULL,
    scope TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (key, scope)
);
CREATE INDEX IF NOT EXISTS idx_auth_event_ts ON auth_event(ts);
CREATE INDEX IF NOT EXISTS idx_comment_incident ON comment(incident_id);
CREATE INDEX IF NOT EXISTS idx_decision_action ON decision(action_id);
"""


def connection() -> sqlite3.Connection:
    conn = getattr(_LOCAL, "conn", None)
    path = config.db_path()
    if conn is None or getattr(_LOCAL, "path", None) != path:
        if conn is not None:
            conn.close()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _LOCAL.conn = conn
        _LOCAL.path = path
    return conn


@contextmanager
def tx():
    """Serialized write transaction; SQLite WAL handles concurrent readers."""
    conn = connection()
    with conn:
        yield conn


def init_db() -> None:
    with tx() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO organization (id, setup_token, setup_used) "
            "VALUES ('default', NULL, 0)"
        )
