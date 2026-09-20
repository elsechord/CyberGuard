"""Durable investigation jobs. One leased dispatcher, no execution credentials."""
import hashlib
import json
import logging
import os
import threading
import time
from uuid import uuid4

from . import audit, db, errors, intake

TERMINAL = {"completed", "failed", "canceled"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS investigation_job (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, idem TEXT NOT NULL,
 fingerprint TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
 payload TEXT NOT NULL, UNIQUE(owner, idem));
CREATE INDEX IF NOT EXISTS idx_investigation_status ON investigation_job(status,created_at);
CREATE TABLE IF NOT EXISTS investigation_dispatch_lease (
 id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, expires REAL NOT NULL);
"""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def init_db():
    with db.tx() as conn:
        conn.executescript(SCHEMA)


def owner_of(principal):
    return f"key:{principal.key_id}" if principal.kind == "api_key" else f"user:{principal.user_id}"


def require(principal, scope):
    if not principal.has_scope(scope):
        raise errors.permission_error(f"missing scope: {scope}", "missing_scope")


def can_read(principal, job):
    return (principal.kind == "session" and principal.role == "admin") or job["owner"] == owner_of(principal)


def public(job, summary=False):
    result = {k: v for k, v in job.items() if k not in {"owner", "bridge_state", "request_fingerprint", "input_sha256"}}
    if summary:
        for key in ("materials", "objective", "report", "events"):
            result.pop(key, None)
    result["links"] = {"self": f"/api/v1/investigations/{job['id']}",
                       "console": f"/investigations/{job['id']}"}
    return result


def input_hash(job):
    fields = {k: job[k] for k in ("title", "objective", "domain", "materials", "request_fingerprint")}
    return hashlib.sha256(canonical(fields).encode()).hexdigest()


def submit(principal, raw_payload, idempotency_key):
    require(principal, "investigations:write")
    if not idempotency_key or len(idempotency_key) > 128 or any(ord(c) < 33 or ord(c) > 126 for c in idempotency_key):
        raise errors.invalid_request("A stable 1..128 character Idempotency-Key is required", status=422)
    try:
        data = intake.validate_submission(raw_payload)
    except ValueError as exc:
        raise errors.invalid_request(str(exc), "invalid_materials", status=422) from None
    owner = owner_of(principal)
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT fingerprint,payload FROM investigation_job WHERE owner=? AND idem=?",
                                (owner, idempotency_key)).fetchone()
        if existing:
            if existing["fingerprint"] != data["request_fingerprint"]:
                raise errors.idempotency_error("Idempotency-Key is bound to another submission")
            return public(json.loads(existing["payload"])), True
        # Bound outstanding work even when no backend is configured.
        count = conn.execute("SELECT COUNT(*) FROM investigation_job WHERE status NOT IN ('completed','failed','canceled')").fetchone()[0]
        if count >= 100:
            raise errors.ApiError(429, "api_error", "queue_full", "Investigation queue is full")
        stamp = audit.now_iso()
        job = {**data, "id": "INV-" + uuid4().hex, "owner": owner,
               "submitted_by": principal.username, "created_at": stamp, "updated_at": stamp,
               "status": "queued", "stage": "accepted", "report": None, "error": None,
               "bridge_state": {}, "runtime": {"backend": "agentteams", "execution": "not_started"},
               "events": [{"at": stamp, "status": "queued", "stage": "accepted", "message": "Materials accepted; backend investigation pending."}]}
        job["input_sha256"] = input_hash(job)
        conn.execute("INSERT INTO investigation_job VALUES (?,?,?,?,?,?,?)",
                     (job["id"], owner, idempotency_key, data["request_fingerprint"], "queued", stamp, canonical(job)))
    audit.record("investigation_submitted", actor=principal.username, target=job["id"])
    return public(job), False


def get_job(principal, job_id):
    require(principal, "investigations:read")
    row = db.connection().execute("SELECT payload FROM investigation_job WHERE id=?", (job_id,)).fetchone()
    if not row or not can_read(principal, job := json.loads(row["payload"])):
        raise errors.invalid_request("Investigation not found", "not_found", status=404)
    return public(job)


def list_jobs(principal, limit=50, cursor=None):
    require(principal, "investigations:read")
    limit = max(1, min(int(limit), 101))
    clauses, args = [], []
    if not (principal.kind == "session" and principal.role == "admin"):
        clauses.append("owner=?")
        args.append(owner_of(principal))
    if cursor:
        item = get_job(principal, cursor)
        clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
        args.extend([item["created_at"], item["created_at"], cursor])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.connection().execute("SELECT payload FROM investigation_job" + where + " ORDER BY created_at DESC,id DESC LIMIT ?", (*args, limit))
    return [public(json.loads(row["payload"]), summary=True) for row in rows]


def list_active_jobs(principal, limit=20):
    require(principal, "investigations:read")
    limit = max(1, min(int(limit), 50))
    if principal.kind == "session" and principal.role == "admin":
        rows = db.connection().execute(
            "SELECT payload FROM investigation_job WHERE status NOT IN ('completed','failed','canceled') "
            "ORDER BY created_at DESC,id DESC LIMIT ?", (limit,))
    else:
        rows = db.connection().execute(
            "SELECT payload FROM investigation_job WHERE owner=? AND status NOT IN ('completed','failed','canceled') "
            "ORDER BY created_at DESC,id DESC LIMIT ?", (owner_of(principal), limit))
    return [public(json.loads(row["payload"]), summary=True) for row in rows]


def cancel(principal, job_id):
    require(principal, "investigations:write")
    row = db.connection().execute("SELECT payload FROM investigation_job WHERE id=?", (job_id,)).fetchone()
    if not row or not can_read(principal, snapshot := json.loads(row["payload"])):
        raise errors.invalid_request("Investigation not found", "not_found", status=404)
    if snapshot["status"] not in TERMINAL and snapshot.get("bridge_state", {}).get("backend") == "native":
        from .agentteams_native import pause
        from .agentteams_bridge import BridgeError
        try:
            pause(snapshot)
        except BridgeError:
            raise errors.invalid_request("Could not pause the native project; retry cancellation", status=503) from None
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload FROM investigation_job WHERE id=?", (job_id,)).fetchone()
        if not row or not can_read(principal, job := json.loads(row["payload"])):
            raise errors.invalid_request("Investigation not found", "not_found", status=404)
        if job["status"] in TERMINAL:
            return public(job)
        job.update(status="canceled", updated_at=audit.now_iso(), error=None)
        job["events"].append({"at": job["updated_at"], "status": "canceled", "stage": job["stage"],
                              "message": "Future stages canceled; a dispatched remote inference may still finish."})
        conn.execute("UPDATE investigation_job SET status=?,payload=? WHERE id=?", ("canceled", canonical(job), job_id))
    audit.record("investigation_canceled", actor=principal.username, target=job_id)
    return public(job)


def lease(owner):
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO investigation_dispatch_lease VALUES (1,'',0)")
        return conn.execute("UPDATE investigation_dispatch_lease SET owner=?,expires=? WHERE id=1 AND (owner=? OR expires<?)",
                            (owner, time.time() + 120, owner, time.time())).rowcount == 1


def budget_ready(job):
    # Only gate work that has not been dispatched. Already-sent requests must
    # still be polled so closing a budget cannot discard their real results.
    if job.get("bridge_state") or os.getenv("CYBERGUARD_INVESTIGATION_REQUIRE_GUARD_ARMED", "false").lower() not in {"true", "1", "yes"}:
        return True
    from .clients import guard_status
    status = guard_status()
    return status.get("available") is True and status.get("armed") is True


def tick(owner, advance=None):
    """One checkpoint per call. Stable backend transaction IDs handle replays."""
    if not lease(owner):
        return False
    row = db.connection().execute("SELECT payload FROM investigation_job WHERE status NOT IN ('completed','failed','canceled') ORDER BY created_at LIMIT 1").fetchone()
    if not row:
        return False
    job = json.loads(row["payload"])
    if input_hash(job) != job["input_sha256"]:
        update = {"state": "failed", "error": "Stored input integrity check failed", "stage": "integrity"}
    elif not budget_ready(job):
        update = {"state": "waiting_backend", "error": "Waiting for an available, armed model budget", "stage": "budget"}
    else:
        if advance is None:
            backend = job.get("bridge_state", {}).get("backend")
            legacy_started = "stage" in job.get("bridge_state", {})
            if backend == "native" or (not legacy_started and os.getenv("CYBERGUARD_AGENTTEAMS_BACKEND", "native") == "native"):
                from .agentteams_native import advance
            else:
                from .agentteams_bridge import advance
        try:
            update = advance(job)
        except Exception:
            # Never expose transport response bodies or backend credentials.
            logging.getLogger(__name__).warning("Investigation backend step failed for %s", job["id"])
            update = {"state": "waiting_backend", "error": "Backend step unavailable; will retry safely", "stage": job["stage"]}
    state = update.get("state", "failed")
    if state not in {"running", "waiting_backend", "completed", "failed"}:
        state = "failed"
        update = {"error": "Invalid backend state", "stage": "validation"}
    if state == "completed" and not isinstance(update.get("report"), dict):
        state = "failed"
        update = {"error": "Backend completion has no validated report", "stage": "validation"}
    with db.tx() as conn:
        conn.execute("BEGIN IMMEDIATE")
        held = conn.execute("SELECT owner,expires FROM investigation_dispatch_lease WHERE id=1").fetchone()
        current = conn.execute("SELECT status FROM investigation_job WHERE id=?", (job["id"],)).fetchone()
        if held["owner"] != owner or held["expires"] <= time.time() or current["status"] in TERMINAL:
            return False
        old = (job["status"], job["stage"], job["error"])
        job.update(status=state, stage=update.get("stage", job["stage"]), error=update.get("error"), updated_at=audit.now_iso())
        for key in ("bridge_state", "runtime", "report"):
            if key in update:
                job[key] = update[key]
        if old != (job["status"], job["stage"], job["error"]):
            job["events"].append({"at": job["updated_at"], "status": state, "stage": job["stage"],
                                  "message": job["error"] or "Backend checkpoint persisted."})
        conn.execute("UPDATE investigation_job SET status=?,payload=? WHERE id=?", (state, canonical(job), job["id"]))
    return True


def start_dispatcher():
    stop = threading.Event()
    owner = uuid4().hex
    def run():
        try:
            while not stop.is_set():
                try:
                    tick(owner)
                except Exception:
                    logging.getLogger(__name__).warning("Investigation dispatcher unavailable; retrying")
                stop.wait(3)
        finally:
            with db.tx() as conn:
                conn.execute("DELETE FROM investigation_dispatch_lease WHERE owner=?", (owner,))
    if os.getenv("CYBERGUARD_INVESTIGATION_DISPATCH_ENABLED", "true").lower() not in {"false", "0", "no"}:
        worker = threading.Thread(target=run, name="investigation-dispatch", daemon=True)
        worker.start()
    else:
        worker = None
    return stop, worker
