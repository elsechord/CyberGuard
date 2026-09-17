"""Loopback-only experimental identity service; never use as a production IdP.

Account access and operations use independent SQLite transactions. Operation IDs
are durable and replay-safe, including when an HTTP response is lost after commit.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


class Conflict(ValueError):
    pass


class IdentityStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts (
                    name TEXT PRIMARY KEY, enabled INTEGER NOT NULL, owner TEXT);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, request TEXT NOT NULL, receipt TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('environment_id', ?)", (uuid4().hex,))
            for name in ("compromised-lab", "control-lab"):
                db.execute("INSERT OR IGNORE INTO accounts VALUES (?, 1, NULL)", (name,))
            self.environment_id = db.execute(
                "SELECT value FROM metadata WHERE key='environment_id'").fetchone()[0]

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def receipt(self, operation_id):
        with self.connect() as db:
            row = db.execute("SELECT receipt FROM operations WHERE id=?", (operation_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def access(self, account):
        with self.connect() as db:
            return bool(db.execute("SELECT enabled FROM accounts WHERE name=?", (account,)).fetchone()[0])

    def apply(self, operation_id, request):
        if set(request) != {"kind", "target", "action_id", "run_id", "environment_id"}:
            raise ValueError("invalid operation fields")
        if not all(isinstance(v, str) and 0 < len(v) <= 128 for v in request.values()):
            raise ValueError("invalid operation values")
        if request["target"] != "compromised-lab" or request["kind"] not in {"disable", "restore"}:
            raise ValueError("only the dedicated lab account can be changed")
        if request["environment_id"] != self.environment_id:
            raise Conflict("environment changed")
        expected_id = request["action_id"] + ("-rollback" if request["kind"] == "restore" else "")
        if operation_id != expected_id:
            raise ValueError("operation ID mismatch")
        canonical = json.dumps(request, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT request, receipt FROM operations WHERE id=?", (operation_id,)).fetchone()
            if previous:
                if previous[0] != canonical:
                    raise Conflict("operation ID already bound to another request")
                return json.loads(previous[1])
            enabled, owner = db.execute("SELECT enabled, owner FROM accounts WHERE name=?",
                                        (request["target"],)).fetchone()
            if request["kind"] == "disable":
                if not enabled or owner:
                    raise Conflict("account already disabled by another operation")
                db.execute("UPDATE accounts SET enabled=0, owner=? WHERE name=?",
                           (request["action_id"], request["target"]))
            else:
                original = db.execute("SELECT request FROM operations WHERE id=?", (request["action_id"],)).fetchone()
                if not original or json.loads(original[0])["run_id"] != request["run_id"]:
                    raise Conflict("rollback has no matching original operation")
                if enabled or owner != request["action_id"]:
                    raise Conflict("account changed since the original operation")
                db.execute("UPDATE accounts SET enabled=1, owner=NULL WHERE name=?", (request["target"],))
            receipt = {**request, "operation_id": operation_id, "result": "applied",
                       "request_sha256": hashlib.sha256(canonical.encode()).hexdigest()}
            db.execute("INSERT INTO operations VALUES (?, ?, ?)",
                       (operation_id, canonical, json.dumps(receipt, sort_keys=True)))
            return receipt


def handler_for(store, admin_token, account_tokens):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log credentials or account requests.

        def reply(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def admin(self):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + admin_token)

        def do_GET(self):
            parts = urlsplit(self.path)
            if parts.path == "/health":
                return self.reply(200, {"environment": "lab", "environment_id": store.environment_id})
            if parts.path == "/access":
                nonce = parse_qs(parts.query).get("nonce", [""])[0]
                if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", nonce):
                    return self.reply(400, {"error": "invalid nonce"})
                supplied = self.headers.get("Authorization", "")
                account = next((name for name, token in account_tokens.items()
                                if hmac.compare_digest(supplied, "Bearer " + token)), None)
                if not account:
                    return self.reply(401, {"error": "invalid account credential"})
                enabled = store.access(account)
                return self.reply(200 if enabled else 403, {
                    "account": account, "allowed": enabled, "nonce": nonce,
                    "environment_id": store.environment_id,
                    "reason": "account_enabled" if enabled else "account_disabled"})
            if re.fullmatch(r"/operations/[a-zA-Z0-9_-]{1,100}", parts.path):
                if not self.admin():
                    return self.reply(401, {"error": "invalid admin credential"})
                receipt = store.receipt(parts.path.rsplit("/", 1)[1])
                return self.reply(200 if receipt else 404, receipt or {"error": "not found"})
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if not self.admin():
                return self.reply(401, {"error": "invalid admin credential"})
            if not re.fullmatch(r"/operations/[a-zA-Z0-9_-]{1,100}", self.path):
                return self.reply(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("invalid body size")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("expected object")
                receipt = store.apply(self.path.rsplit("/", 1)[1], payload)
                self.reply(200, receipt)
            except Conflict as exc:
                self.reply(409, {"error": str(exc)})
            except (ValueError, TypeError):
                self.reply(400, {"error": "invalid operation"})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18110)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    names = ("CYBERGUARD_LAB_ADMIN_TOKEN", "CYBERGUARD_LAB_TARGET_TOKEN", "CYBERGUARD_LAB_CONTROL_TOKEN")
    tokens = [os.getenv(name, "") for name in names]
    if any(len(token) < 32 for token in tokens) or len(set(tokens)) != 3:
        parser.error("set three distinct lab tokens of at least 32 characters")
    store = IdentityStore(args.db)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(
        store, tokens[0], {"compromised-lab": tokens[1], "control-lab": tokens[2]}))
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
