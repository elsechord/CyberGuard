import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="CyberGuard Controlled Response Executor",
    version="0.11.0",
    docs_url=None,
    redoc_url=None,
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response
DATA_DIR = Path(os.getenv("CYBERGUARD_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOCK = RLock()

ALLOWED_ACTIONS = {
    "block_ioc": {"risk": "L1", "reversible": True},
    "disable_account": {"risk": "L2", "reversible": True},
    "isolate_endpoint": {"risk": "L2", "reversible": True},
    "quarantine_workload": {"risk": "L2", "reversible": True},
}


class ActionRequest(BaseModel):
    incident_id: str = Field(min_length=3, max_length=128)
    action: Literal["block_ioc", "disable_account", "isolate_endpoint", "quarantine_workload"]
    target: str = Field(min_length=1, max_length=512)
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ApprovalRequest(BaseModel):
    action_id: str
    approver: str = Field(min_length=2, max_length=128)
    expires_minutes: int = Field(default=15, ge=1, le=60)


def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("CYBERGUARD_EXECUTOR_TOKEN", "")
    supplied = (authorization or "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


def authorize_audit_reader(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("CYBERGUARD_AUDIT_READER_TOKEN", "")
    supplied = (authorization or "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid audit reader token")


def append_event(event: dict) -> None:
    with LOCK:
        audit_key = os.getenv("CYBERGUARD_AUDIT_HMAC_KEY", "")
        if len(audit_key) < 32:
            raise RuntimeError("CYBERGUARD_AUDIT_HMAC_KEY must contain at least 32 characters")
        event["recorded_at"] = datetime.now(UTC).isoformat()
        previous = load_events()
        event["previous_record_sha256"] = previous[-1].get("record_sha256") if previous else None
        canonical = json.dumps(event, ensure_ascii=False, sort_keys=True)
        event["record_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        authenticated = json.dumps(event, ensure_ascii=False, sort_keys=True)
        event["record_hmac_sha256"] = hmac.new(
            audit_key.encode(), authenticated.encode(), hashlib.sha256
        ).hexdigest()
        stream = (DATA_DIR / "actions.jsonl").open("a", encoding="utf-8")
        try:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            stream.close()


def load_events() -> list[dict]:
    with LOCK:
        path = DATA_DIR / "actions.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "response-executor", "mode": "simulation"}


@app.post("/actions/propose", dependencies=[Depends(authorize)])
def propose(request: ActionRequest) -> dict:
    with LOCK:
        for event in reversed(load_events()):
            if event.get("idempotency_key") == request.idempotency_key:
                original = {key: event.get(key) for key in request.model_dump()}
                if original != request.model_dump():
                    raise HTTPException(
                        status_code=409,
                        detail="idempotency key is already bound to a different proposal",
                    )
                return event
        action_id = f"ACT-{uuid4().hex[:12]}"
        event = {
            "action_id": action_id,
            **request.model_dump(),
            **ALLOWED_ACTIONS[request.action],
            "status": "pending_approval",
        }
        append_event(event)
        return event


@app.post("/actions/approve", dependencies=[Depends(authorize)])
def approve(request: ApprovalRequest, x_approval_secret: str | None = Header(default=None)) -> dict:
    expected = os.getenv("CYBERGUARD_APPROVAL_SECRET", "")
    if not expected or not hmac.compare_digest(x_approval_secret or "", expected):
        raise HTTPException(status_code=403, detail="invalid approval secret")
    with LOCK:
        events = [event for event in load_events() if event.get("action_id") == request.action_id]
        if not events:
            raise HTTPException(status_code=404, detail="action not found")
        proposal = next((event for event in events if event.get("status") == "pending_approval"), None)
        if proposal is None:
            raise HTTPException(status_code=409, detail="action has no pending proposal")
        if any(event.get("status") in {"executed", "rolled_back"} for event in events):
            raise HTTPException(status_code=409, detail="action already executed or closed")
        latest_approval = next((event for event in reversed(events) if event.get("status") == "approved"), None)
        if latest_approval is not None:
            expiry = datetime.fromisoformat(latest_approval["approval_expires_at"])
            if expiry >= datetime.now(UTC):
                raise HTTPException(status_code=409, detail="a valid approval already exists")
        event = {
            "action_id": request.action_id,
            "incident_id": proposal["incident_id"],
            "proposal_record_sha256": proposal["record_sha256"],
            "approver": request.approver,
            "status": "approved",
            "approval_expires_at": (datetime.now(UTC) + timedelta(minutes=request.expires_minutes)).isoformat(),
        }
        if latest_approval is not None:
            event["supersedes_approval_record_sha256"] = latest_approval["record_sha256"]
        append_event(event)
        return event


@app.get("/actions/{action_id}", dependencies=[Depends(authorize)])
def action_history(action_id: str) -> dict:
    events = [event for event in load_events() if event.get("action_id") == action_id]
    if not events:
        raise HTTPException(status_code=404, detail="action not found")
    return {"action_id": action_id, "events": events}


@app.get("/audit/verify", dependencies=[Depends(authorize)])
def verify_audit() -> dict:
    audit_key = os.getenv("CYBERGUARD_AUDIT_HMAC_KEY", "")
    if len(audit_key) < 32:
        return {"valid": False, "failed_record": None, "reason": "audit_key_unavailable"}
    previous_hash = None
    events = load_events()
    for index, persisted in enumerate(events):
        record = dict(persisted)
        claimed_hmac = record.pop("record_hmac_sha256", None)
        claimed_hash = record.pop("record_sha256", None)
        if record.get("previous_record_sha256") != previous_hash:
            return {"valid": False, "failed_record": index, "reason": "broken_previous_hash"}
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
        calculated = hashlib.sha256(canonical.encode()).hexdigest()
        if not claimed_hash or not hmac.compare_digest(claimed_hash, calculated):
            return {"valid": False, "failed_record": index, "reason": "record_hash_mismatch"}
        record["record_sha256"] = claimed_hash
        authenticated = json.dumps(record, ensure_ascii=False, sort_keys=True)
        calculated_hmac = hmac.new(audit_key.encode(), authenticated.encode(), hashlib.sha256).hexdigest()
        if not claimed_hmac or not hmac.compare_digest(claimed_hmac, calculated_hmac):
            return {"valid": False, "failed_record": index, "reason": "record_hmac_mismatch"}
        previous_hash = claimed_hash
    return {"valid": True, "records": len(events), "head": previous_hash, "authenticated": True}


@app.get("/audit/checkpoint", dependencies=[Depends(authorize)])
def audit_checkpoint() -> dict:
    verification = verify_audit()
    if not verification["valid"]:
        raise HTTPException(status_code=409, detail=verification)
    checkpoint = {
        "records": verification["records"],
        "head": verification["head"],
        "generated_at": datetime.now(UTC).isoformat(),
        "algorithm": "HMAC-SHA256",
    }
    canonical = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True)
    checkpoint["checkpoint_hmac_sha256"] = hmac.new(
        os.environ["CYBERGUARD_AUDIT_HMAC_KEY"].encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()
    return checkpoint


@app.get("/audit/incidents/{incident_id}/active", dependencies=[Depends(authorize_audit_reader)])
def verified_incident_state(incident_id: str) -> dict:
    verification = verify_audit()
    if not verification["valid"]:
        raise HTTPException(status_code=409, detail=verification)
    active: dict[str, dict] = {}
    for event in load_events():
        if event.get("incident_id") != incident_id or not event.get("action_id"):
            continue
        if event.get("status") == "executed":
            active[event["action_id"]] = {
                "action_id": event["action_id"], "action": event.get("action"),
                "target": event.get("target"), "status": "executed",
            }
        elif event.get("status") == "rolled_back":
            active.pop(event["action_id"], None)
    return {
        "incident_id": incident_id,
        "audit_head": verification["head"],
        "audit_records": verification["records"],
        "active_executed_action": bool(active),
        "active_actions": sorted(active.values(), key=lambda item: item["action_id"]),
    }


@app.post("/actions/{action_id}/execute", dependencies=[Depends(authorize)])
def execute(action_id: str) -> dict:
    with LOCK:
        events = [event for event in load_events() if event.get("action_id") == action_id]
        proposal = next((event for event in events if event.get("status") == "pending_approval"), None)
        approval = next((event for event in reversed(events) if event.get("status") == "approved"), None)
        if proposal is None:
            raise HTTPException(status_code=404, detail="action not found")
        if any(event.get("status") == "rolled_back" for event in events):
            raise HTTPException(status_code=409, detail="action is closed after rollback")
        already_executed = next((event for event in reversed(events) if event.get("status") == "executed"), None)
        if already_executed is not None:
            return already_executed
        if approval is None:
            raise HTTPException(status_code=409, detail="approval required")
        if approval.get("proposal_record_sha256") != proposal.get("record_sha256"):
            raise HTTPException(status_code=409, detail="approval is not bound to this proposal")
        if datetime.fromisoformat(approval["approval_expires_at"]) < datetime.now(UTC):
            raise HTTPException(status_code=409, detail="approval expired")
        event = {
            "action_id": action_id,
            "incident_id": proposal["incident_id"],
            "action": proposal["action"],
            "target": proposal["target"],
            "approval_record_sha256": approval["record_sha256"],
            "status": "executed",
            "result": "simulated_success",
            "rollback_available": proposal["reversible"],
        }
        append_event(event)
        return event


@app.post("/actions/{action_id}/rollback", dependencies=[Depends(authorize)])
def rollback(action_id: str) -> dict:
    with LOCK:
        events = [event for event in load_events() if event.get("action_id") == action_id]
        executed = next((event for event in reversed(events) if event.get("status") == "executed"), None)
        if executed is None:
            raise HTTPException(status_code=409, detail="action has not been executed")
        already_rolled_back = next((event for event in reversed(events) if event.get("status") == "rolled_back"), None)
        if already_rolled_back is not None:
            return already_rolled_back
        event = {
            "action_id": action_id,
            "incident_id": executed["incident_id"],
            "execution_record_sha256": executed["record_sha256"],
            "status": "rolled_back",
            "result": "simulated_success",
        }
        append_event(event)
        return event
