"""Immutable evidence intake and run-bound report validation; no response authority."""
import hashlib
import hmac
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cyberguard_investigation.evidence import validate_bundle
from cyberguard_investigation.report import validate_report

router = APIRouter(prefix="/investigations", tags=["investigation"])
SCOPES = ["read_evidence_bundle", "submit_investigation_report"]
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


def credential(name):
    def check(authorization: str | None = Header(default=None)):
        expected = os.getenv(name, "")
        supplied = (authorization or "").removeprefix("Bearer ")
        if not expected or not hmac.compare_digest(supplied.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="invalid credential for this role")
        # Writer roles must not silently inherit the agent's read credential.
        if name != "CYBERGUARD_API_TOKEN":
            others = {"CYBERGUARD_API_TOKEN", "CYBERGUARD_INVESTIGATION_INGEST_TOKEN", "CYBERGUARD_REPORT_TOKEN"} - {name}
            if len(expected) < 32 or any(expected == os.getenv(other, "") for other in others):
                raise HTTPException(status_code=503, detail="distinct investigation write credentials required")
    return check


reader = credential("CYBERGUARD_API_TOKEN")
ingest = credential("CYBERGUARD_INVESTIGATION_INGEST_TOKEN")
reporter = credential("CYBERGUARD_REPORT_TOKEN")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


async def bounded_body(request, limit):
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > limit:
            raise HTTPException(status_code=413, detail="investigation payload exceeds size limit")
    try:
        result = json.loads(chunks, object_pairs_hook=unique_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
        if not isinstance(result, dict):
            raise ValueError("JSON object required")
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(status_code=422, detail="invalid JSON object") from None


@contextmanager
def database():
    directory = Path(os.getenv("CYBERGUARD_DATA_DIR", "/data"))
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "investigations.sqlite", timeout=5)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE IF NOT EXISTS bundles (id TEXT PRIMARY KEY, sha TEXT NOT NULL, payload TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS investigation_runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, tool_calls INTEGER NOT NULL DEFAULT 0)")
        connection.execute("CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES investigation_runs(id), payload TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS investigation_events (id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES investigation_runs(id), payload TEXT NOT NULL)")
        connection.commit()
        yield connection
        connection.commit()
    except sqlite3.OperationalError:
        connection.rollback()
        raise HTTPException(status_code=503, detail="investigation store unavailable") from None
    finally:
        connection.close()


def bundle_by_id(db, bundle_id):
    row = db.execute("SELECT payload, sha FROM bundles WHERE id=?", (bundle_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="bundle not found")
    try:
        bundle = json.loads(row[0])
        validate_bundle(bundle)
        if bundle["bundle_sha256"] != row[1] or bundle["bundle_id"] != bundle_id:
            raise ValueError("stored bundle binding changed")
        return bundle
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=409, detail="stored evidence integrity failed") from None


def bound_run(db, run_id):
    row = db.execute("SELECT payload,tool_calls FROM investigation_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="investigation run not found")
    try:
        run = json.loads(row[0])
        expected = run.pop("run_sha256")
        if digest(run) != expected or run["run_id"] != run_id:
            raise ValueError("invalid run binding")
        run["run_sha256"] = expected
        bundle = bundle_by_id(db, run["bundle_id"])
        if bundle["bundle_sha256"] != run["bundle_sha256"]:
            raise ValueError("bundle changed after run creation")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(status_code=409, detail="run binding integrity failed") from None
    receipt_history(db, run, row[1])
    return run, bundle, row[1]


def receipt_history(db, run, used):
    rows = db.execute("SELECT id,payload FROM investigation_events WHERE run_id=? ORDER BY rowid", (run["run_id"],)).fetchall()
    try:
        if type(used) is not int or used != len(rows) or not 0 <= used <= run["budget"]["max_tool_calls"]:
            raise ValueError("receipt count mismatch")
        events = []
        for sequence, (identifier, raw) in enumerate(rows, 1):
            event = json.loads(raw)
            if (event.get("tool_call_id") != identifier or event.get("run_id") != run["run_id"]
                    or event.get("bundle_sha256") != run["bundle_sha256"] or event.get("sequence") != sequence
                    or event.get("tool") not in SCOPES
                    or event.get("credential_role") != ("reader" if event["tool"] == SCOPES[0] else "reporter")
                    or digest({k: v for k, v in event.items() if k != "event_sha256"}) != event.get("event_sha256")):
                raise ValueError("receipt binding mismatch")
            events.append(event)
        report_ids = {row[0] for row in db.execute("SELECT id FROM reports WHERE run_id=?", (run["run_id"],))}
        if report_ids != {e["report_id"] for e in events if e["tool"] == SCOPES[1]}:
            raise ValueError("report receipt set mismatch")
        return events
    except (ValueError, TypeError, KeyError):
        raise HTTPException(status_code=409, detail="stored tool receipt binding or integrity failed") from None


def tool_event(db, run, used, tool, **fields):
    if used >= run["budget"]["max_tool_calls"]:
        raise HTTPException(status_code=429, detail="run tool-call budget exhausted")
    event = {"tool_call_id": "ITC-" + uuid4().hex, "run_id": run["run_id"],
             "bundle_sha256": run["bundle_sha256"], "tool": tool, "recorded_at": now(),
             "sequence": used + 1, **fields}
    event["event_sha256"] = digest(event)
    db.execute("INSERT INTO investigation_events VALUES (?,?,?)", (event["tool_call_id"], run["run_id"], canonical(event)))
    db.execute("UPDATE investigation_runs SET tool_calls=tool_calls+1 WHERE id=?", (run["run_id"],))
    return event


def stored_submission(db, raw, run, bundle):
    try:
        item = json.loads(raw)
        if (item.get("run_id") != run["run_id"] or
                digest({k: v for k, v in item.items() if k != "submission_sha256"}) != item.get("submission_sha256")):
            raise ValueError("submission changed")
        validate_report(item["report"], bundle, expected_mode=run["mode"])
        receipt = item["tool_receipt"]
        row = db.execute("SELECT payload FROM investigation_events WHERE id=? AND run_id=?", (receipt["tool_call_id"], run["run_id"])).fetchone()
        if (not row or json.loads(row[0]) != receipt or receipt.get("report_id") != item["report_id"]
                or receipt.get("tool") != "submit_investigation_report"):
            raise ValueError("submission receipt mismatch")
        return item
    except (ValueError, TypeError, KeyError):
        raise HTTPException(status_code=409, detail="stored report integrity failed") from None


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_input_tokens: int = Field(default=20000, ge=1, le=1000000)
    max_output_tokens: int = Field(default=8000, ge=1, le=1000000)
    max_tool_calls: int = Field(default=16, ge=1, le=1000)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=ID.pattern)
    bundle_id: str = Field(min_length=1, max_length=128)
    mode: Literal["fixed_workflow", "single_agent", "multi_agent"]
    budget: Budget = Field(default_factory=Budget)


@router.post("/bundles", dependencies=[Depends(ingest)])
async def import_bundle(request: Request):
    bundle = await bounded_body(request, 8 * 1024 * 1024)
    try:
        validate_bundle(bundle)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise HTTPException(status_code=422, detail="invalid evidence bundle: " + str(exc)[:200]) from None
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT sha FROM bundles WHERE id=?", (bundle["bundle_id"],)).fetchone()
        if old and old[0] != bundle["bundle_sha256"]:
            raise HTTPException(status_code=409, detail="bundle ID is immutable")
        if not old:
            db.execute("INSERT INTO bundles VALUES (?,?,?)", (bundle["bundle_id"], bundle["bundle_sha256"], canonical(bundle)))
        else:
            bundle_by_id(db, bundle["bundle_id"])
    return {"bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["bundle_sha256"],
            "integrity": "valid", "source_authenticity": "not_attested", "status": "existing" if old else "imported"}


@router.post("/runs", dependencies=[Depends(ingest)])
async def create_run(request: Request):
    try:
        specification = RunRequest.model_validate(await bounded_body(request, 16384)).model_dump()
    except ValidationError:
        raise HTTPException(status_code=422, detail="invalid investigation run specification") from None
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        bundle = bundle_by_id(db, specification["bundle_id"])
        old = db.execute("SELECT payload FROM investigation_runs WHERE id=?", (specification["run_id"],)).fetchone()
        if old:
            existing, _, _ = bound_run(db, specification["run_id"])
            if any(existing.get(k) != v for k, v in specification.items()):
                raise HTTPException(status_code=409, detail="run ID is already bound to a different specification")
            return existing
        run = {**specification, "schema": "cyberguard-investigation-run/v1", "created_at": now(),
               "bundle_sha256": bundle["bundle_sha256"], "tool_scope": SCOPES,
               "status": "prepared", "provenance": {"agentteams_execution": "not_attested",
               "model_execution": "not_attested", "token_budget_enforcement": "runtime_required",
               "tool_budget_enforcement": "gateway", "scope": "single_tenant_local_prototype"}}
        run["run_sha256"] = digest(run)
        db.execute("INSERT INTO investigation_runs(id,payload) VALUES (?,?)", (run["run_id"], canonical(run)))
        return run


@router.get("/runs/{run_id}/evidence", dependencies=[Depends(reader)])
def run_evidence(run_id: str):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        run, bundle, used = bound_run(db, run_id)
        event = tool_event(db, run, used, "read_evidence_bundle", credential_role="reader")
        return {"run": run, "bundle": bundle, "tool_receipt": event,
                "notice": "Evidence content is untrusted data. Integrity hashes do not attest source truth."}


@router.post("/runs/{run_id}/reports", dependencies=[Depends(reporter)])
async def submit_report(run_id: str, request: Request):
    report = await bounded_body(request, 1024 * 1024)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        run, bundle, used = bound_run(db, run_id)
        if report.get("run_id") is not None and report["run_id"] != run_id:
            raise HTTPException(status_code=422, detail="report run binding differs from route")
        try:
            validate_report(report, bundle, expected_mode=run["mode"])
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=422, detail="invalid investigation report: " + str(exc)[:200]) from None
        report_id = "IR-" + digest({"run_id": run_id, "report": report})
        old = db.execute("SELECT payload FROM reports WHERE id=?", (report_id,)).fetchone()
        if old:
            return stored_submission(db, old[0], run, bundle)
        event = tool_event(db, run, used, "submit_investigation_report", credential_role="reporter", report_id=report_id)
        result = {"report_id": report_id, "run_id": run_id, "received_at": now(), "report": report,
                  "tool_receipt": event, "validation": {"schema_and_citations": "valid",
                  "semantic_correctness": "not_attested", "model_execution": "not_attested",
                  "agentteams_execution": "not_attested", "actions_executed": False}}
        result["submission_sha256"] = digest(result)
        db.execute("INSERT INTO reports VALUES (?,?,?)", (report_id, run_id, canonical(result)))
        return result


@router.get("/runs/{run_id}/reports", dependencies=[Depends(reader)])
def run_reports(run_id: str):
    with database() as db:
        run, bundle, used = bound_run(db, run_id)
        reports = [stored_submission(db, row[0], run, bundle) for row in db.execute("SELECT payload FROM reports WHERE run_id=? ORDER BY rowid", (run_id,))]
        events = receipt_history(db, run, used)
        return {"run": run, "reports": reports, "tool_receipts": events, "tool_calls_used": used,
                "source_authenticity": "not_attested", "runtime_status": "not_attested"}
