"""Durable, process-safe admission for one run's model requests. No network I/O.

The caller must authenticate before reserve, then commit ``begin_dispatch``
immediately before forwarding and forward only on ``dispatch=True``. Reserve's
``forward=True`` means first reservation eligibility, not dispatch commitment.
Settle only with trusted provider usage. Unknown/failed attempts keep their
reservation and concurrency slot; elapsed time never releases them.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class AdmissionError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _identifier(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise AdmissionError("invalid_" + field)


def _hash(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise AdmissionError("invalid_" + field)


def _count(value, field, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 1_000_000_000:
        raise AdmissionError("invalid_" + field)


def _limits(value):
    required = {"max_requests", "max_input_tokens", "max_output_tokens"}
    if not isinstance(value, dict) or not required <= set(value) <= required | {"max_concurrency", "max_requests_per_role"}:
        raise AdmissionError("invalid_limits")
    result = {**value, "max_concurrency": value.get("max_concurrency", 1),
              "max_requests_per_role": value.get("max_requests_per_role", value["max_requests"])}
    for name, count in result.items():
        if name == "max_requests_per_role" and isinstance(count, dict):
            if len(count) > 32:
                raise AdmissionError("invalid_max_requests_per_role")
            for role, maximum in count.items():
                _identifier(role, "role")
                _count(maximum, name, positive=True)
        else:
            _count(count, name, positive=name in {"max_requests", "max_concurrency", "max_requests_per_role"})
    return result


def _credential_hash(token, salt):
    try:
        encoded = token.encode("utf-8")
    except UnicodeError:
        raise AdmissionError("invalid_role_credential") from None
    return hmac.new(bytes.fromhex(salt), encoded, hashlib.sha256).hexdigest()


class AdmissionLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
        with self._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS admission_runs (
                run_id TEXT PRIMARY KEY, model TEXT NOT NULL, evidence_hash TEXT NOT NULL,
                limits_json TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
                created_at TEXT NOT NULL, closed_at TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS admission_roles (
                run_id TEXT NOT NULL REFERENCES admission_runs(run_id), role TEXT NOT NULL,
                salt TEXT NOT NULL, credential_hash TEXT NOT NULL, PRIMARY KEY(run_id,role))""")
            db.execute("""CREATE TABLE IF NOT EXISTS admission_requests (
                run_id TEXT NOT NULL, request_id TEXT NOT NULL, role TEXT NOT NULL,
                body_sha256 TEXT NOT NULL, input_reservation INTEGER NOT NULL,
                output_reservation INTEGER NOT NULL, status TEXT NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER, reason TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(run_id,request_id),
                FOREIGN KEY(run_id,role) REFERENCES admission_roles(run_id,role))""")

    @contextmanager
    def _transaction(self, *, write=True):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except sqlite3.OperationalError:
            db.rollback()
            raise AdmissionError("ledger_unavailable") from None
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _run(db, run_id):
        row = db.execute("SELECT * FROM admission_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise AdmissionError("run_not_found")
        return row

    @staticmethod
    def _request(db, run_id, request_id):
        row = db.execute("SELECT * FROM admission_requests WHERE run_id=? AND request_id=?", (run_id, request_id)).fetchone()
        if row is None:
            raise AdmissionError("request_not_found")
        return row

    @staticmethod
    def _summary(db, row):
        counts = db.execute("""SELECT COUNT(*) AS requests,
            COALESCE(SUM(CASE WHEN status='settled' THEN input_tokens ELSE input_reservation END),0) AS charged_input,
            COALESCE(SUM(CASE WHEN status='settled' THEN output_tokens ELSE output_reservation END),0) AS charged_output,
            COALESCE(SUM(CASE WHEN status='settled' THEN input_tokens ELSE 0 END),0) AS known_input,
            COALESCE(SUM(CASE WHEN status='settled' THEN output_tokens ELSE 0 END),0) AS known_output,
            COALESCE(SUM(CASE WHEN status!='settled' THEN input_reservation ELSE 0 END),0) AS reserved_input,
            COALESCE(SUM(CASE WHEN status!='settled' THEN output_reservation ELSE 0 END),0) AS reserved_output,
            COALESCE(SUM(CASE WHEN status!='settled' THEN 1 ELSE 0 END),0) AS concurrency_used
            FROM admission_requests WHERE run_id=?""", (row["run_id"],)).fetchone()
        limits = json.loads(row["limits_json"])
        return {"run_id": row["run_id"], "model": row["model"], "evidence_hash": row["evidence_hash"],
                "limits": limits, "status": row["status"], "reason": row["reason"],
                "created_at": row["created_at"], "closed_at": row["closed_at"],
                "roles": [r[0] for r in db.execute("SELECT role FROM admission_roles WHERE run_id=? ORDER BY role", (row["run_id"],))],
                "requests_by_role": {r[0]: r[1] for r in db.execute("SELECT role,COUNT(*) FROM admission_requests WHERE run_id=? GROUP BY role", (row["run_id"],))},
                "usage": dict(counts),
                "remaining": {"requests": max(0, limits["max_requests"] - counts["requests"]),
                              "input_tokens": max(0, limits["max_input_tokens"] - counts["charged_input"]),
                              "output_tokens": max(0, limits["max_output_tokens"] - counts["charged_output"]),
                              "concurrency": max(0, limits["max_concurrency"] - counts["concurrency_used"])}}

    def create_run(self, run_id, *, model, evidence_hash, limits, role_credentials):
        _identifier(run_id, "run_id")
        if not isinstance(model, str) or not model.strip() or len(model) > 256:
            raise AdmissionError("invalid_model")
        _hash(evidence_hash, "evidence_hash")
        normalized = _limits(limits)
        if not isinstance(role_credentials, dict) or not 1 <= len(role_credentials) <= 32:
            raise AdmissionError("invalid_role_credentials")
        for role, token in role_credentials.items():
            _identifier(role, "role")
            if not isinstance(token, str) or not 32 <= len(token) <= 4096:
                raise AdmissionError("invalid_role_credential")
        if len(set(role_credentials.values())) != len(role_credentials):
            raise AdmissionError("role_credentials_must_be_distinct")
        if isinstance(normalized["max_requests_per_role"], dict) and not set(normalized["max_requests_per_role"]) <= set(role_credentials):
            raise AdmissionError("invalid_max_requests_per_role")
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        with self._transaction() as db:
            old = db.execute("SELECT * FROM admission_runs WHERE run_id=?", (run_id,)).fetchone()
            if old is not None:
                if old["model"] != model or old["evidence_hash"] != evidence_hash or old["limits_json"] != encoded:
                    raise AdmissionError("run_binding_conflict")
                bound = list(db.execute("SELECT role,salt,credential_hash FROM admission_roles WHERE run_id=?", (run_id,)))
                if {r["role"] for r in bound} != set(role_credentials) or any(
                        not hmac.compare_digest(r["credential_hash"], _credential_hash(role_credentials[r["role"]], r["salt"])) for r in bound):
                    raise AdmissionError("run_role_binding_conflict")
                return self._summary(db, old)
            db.execute("INSERT INTO admission_runs VALUES (?,?,?,?,?,?,?,?)", (run_id, model, evidence_hash, encoded, "open", None, _now(), None))
            for role, token in role_credentials.items():
                salt = secrets.token_hex(32)
                db.execute("INSERT INTO admission_roles VALUES (?,?,?,?)", (run_id, role, salt, _credential_hash(token, salt)))
            return self._summary(db, self._run(db, run_id))

    def authenticate(self, run_id, role, token):
        if not isinstance(token, str) or len(token) > 4096 or not isinstance(run_id, str) or not isinstance(role, str):
            return False
        with self._transaction(write=False) as db:
            row = db.execute("SELECT salt,credential_hash FROM admission_roles WHERE run_id=? AND role=?", (run_id, role)).fetchone()
        salt, expected = (row["salt"], row["credential_hash"]) if row else ("0" * 64, "0" * 64)
        try:
            actual = _credential_hash(token, salt)
        except AdmissionError:
            return False
        return hmac.compare_digest(expected, actual) and row is not None

    def reserve(self, run_id, role, request_id, body_sha256, input_reservation, output_reservation):
        """Only fresh reservations return forward=True; begin_dispatch is still required."""
        for value, name in ((run_id, "run_id"), (role, "role"), (request_id, "request_id")):
            _identifier(value, name)
        _hash(body_sha256, "body_sha256")
        _count(input_reservation, "input_reservation")
        _count(output_reservation, "output_reservation")
        with self._transaction() as db:
            run = self._run(db, run_id)
            old = db.execute("SELECT * FROM admission_requests WHERE run_id=? AND request_id=?", (run_id, request_id)).fetchone()
            if old is not None:
                expected = {"role": role, "body_sha256": body_sha256, "input_reservation": input_reservation,
                            "output_reservation": output_reservation}
                if any(old[k] != v for k, v in expected.items()):
                    raise AdmissionError("request_binding_conflict")
                return {**dict(old), "forward": False, "run_status": run["status"]}
            if not db.execute("SELECT 1 FROM admission_roles WHERE run_id=? AND role=?", (run_id, role)).fetchone():
                raise AdmissionError("role_not_bound")
            if run["status"] != "open":
                raise AdmissionError("run_closed")
            summary = self._summary(db, run)
            remaining = summary["remaining"]
            if not remaining["requests"]:
                raise AdmissionError("request_budget_exhausted")
            role_limit = summary["limits"]["max_requests_per_role"]
            if isinstance(role_limit, dict):
                role_limit = role_limit.get(role, summary["limits"]["max_requests"])
            if summary["requests_by_role"].get(role, 0) >= role_limit:
                raise AdmissionError("role_request_budget_exhausted")
            if input_reservation > remaining["input_tokens"] or output_reservation > remaining["output_tokens"]:
                raise AdmissionError("token_budget_exhausted")
            if not remaining["concurrency"]:
                raise AdmissionError("concurrency_exhausted")
            stamp = _now()
            db.execute("INSERT INTO admission_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                run_id, request_id, role, body_sha256, input_reservation, output_reservation, "pending", None, None, None, stamp, stamp))
            return {**dict(self._request(db, run_id, request_id)), "forward": True, "run_status": "open"}

    def begin_dispatch(self, run_id, request_id):
        """Atomically order dispatch against closure; commit once, never auto-replay.

        Once committed, the request is in flight even if close_run follows before
        the transport returns. A crash after commitment retains its reservation.
        """
        _identifier(run_id, "run_id")
        _identifier(request_id, "request_id")
        with self._transaction() as db:
            run = self._run(db, run_id)
            request = self._request(db, run_id, request_id)
            if run["status"] != "open":
                raise AdmissionError("run_closed")
            if request["status"] == "dispatched":
                return {**dict(request), "dispatch": False, "forward": False, "run_status": "open"}
            if request["status"] != "pending":
                raise AdmissionError("request_not_pending")
            db.execute("UPDATE admission_requests SET status='dispatched',updated_at=? WHERE run_id=? AND request_id=?",
                       (_now(), run_id, request_id))
            return {**dict(self._request(db, run_id, request_id)), "dispatch": True, "forward": True, "run_status": "open"}

    def settle(self, run_id, request_id, input_tokens, output_tokens):
        _count(input_tokens, "input_tokens")
        _count(output_tokens, "output_tokens")
        with self._transaction() as db:
            self._run(db, run_id)
            request = self._request(db, run_id, request_id)
            if request["status"] == "settled":
                if request["input_tokens"] != input_tokens or request["output_tokens"] != output_tokens:
                    raise AdmissionError("usage_settlement_conflict")
                return {**dict(request), "settled_now": False, "run": self._summary(db, self._run(db, run_id))}
            exceeds = input_tokens > request["input_reservation"] or output_tokens > request["output_reservation"]
            db.execute("UPDATE admission_requests SET status='settled',input_tokens=?,output_tokens=?,reason=?,updated_at=? WHERE run_id=? AND request_id=?",
                       (input_tokens, output_tokens, "provider_usage_exceeded_reservation" if exceeds else None, _now(), run_id, request_id))
            if exceeds:
                db.execute("UPDATE admission_runs SET status='halted',reason='provider_usage_exceeded_reservation',closed_at=? WHERE run_id=?", (_now(), run_id))
            return {**dict(self._request(db, run_id, request_id)), "settled_now": True,
                    "run": self._summary(db, self._run(db, run_id))}

    def _mark_unaccounted(self, run_id, request_id, status, reason):
        _identifier(reason, "reason")
        with self._transaction() as db:
            self._run(db, run_id)
            request = self._request(db, run_id, request_id)
            if request["status"] == "settled":
                raise AdmissionError("request_already_settled")
            db.execute("UPDATE admission_requests SET status=?,reason=?,updated_at=? WHERE run_id=? AND request_id=?",
                       (status, reason, _now(), run_id, request_id))
            return {**dict(self._request(db, run_id, request_id)), "run": self._summary(db, self._run(db, run_id))}

    def mark_unknown(self, run_id, request_id, reason="provider_usage_unknown"):
        return self._mark_unaccounted(run_id, request_id, "unknown", reason)

    def mark_failed(self, run_id, request_id, reason="provider_request_failed"):
        return self._mark_unaccounted(run_id, request_id, "failed", reason)

    def close_run(self, run_id, reason="closed"):
        _identifier(reason, "reason")
        with self._transaction() as db:
            run = self._run(db, run_id)
            if run["status"] == "open":
                db.execute("UPDATE admission_runs SET status='closed',reason=?,closed_at=? WHERE run_id=?", (reason, _now(), run_id))
            return self._summary(db, self._run(db, run_id))

    def get_run(self, run_id):
        with self._transaction(write=False) as db:
            return self._summary(db, self._run(db, run_id))

    def get_request(self, run_id, request_id):
        with self._transaction(write=False) as db:
            return dict(self._request(db, run_id, request_id))
