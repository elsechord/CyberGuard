"""API v1: dual-auth (session cookie or Bearer API key), envelope responses,
cursor pagination, Idempotency-Key replay protection and upstream proxying.

Session-authenticated non-GET requests require same-origin Origin/Referer plus
an X-Requested-With header (CSRF defence for JSON fetches); Bearer API key
requests are exempt. Write endpoints honour Idempotency-Key for 24 hours.
"""
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import apikeys, audit, auth, clients, config, errors, idempotency

router = APIRouter(prefix="/api/v1", tags=["api-v1"])

DECISION_CLASSIFICATIONS = [
    "approved_true_positive", "approved_with_caution",
    "denied_false_positive_logic", "denied_false_positive_data", "undetermined",
]


# ---------------------------------------------------------------- principals

def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def resolve_principal(request: Request) -> auth.Principal:
    """Bearer cg_live_ key first, then the session cookie."""
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        raw = authorization[len("Bearer "):].strip()
        row = apikeys.verify_key(raw)
        if row is None:
            audit.record("api_key_auth", result="failure",
                         reason="unknown_or_revoked_key", ip=client_ip(request))
            raise errors.authentication_error("invalid API key", "invalid_api_key")
        try:
            scopes = set(json.loads(row["scopes"]))
        except (TypeError, ValueError):
            scopes = set()
        return auth.Principal(kind="api_key", user_id=None,
                              username=f"api-key:{row['prefix']}", role="viewer",
                              scopes=scopes, key_id=row["id"])
    sid = request.cookies.get(config.cookie_name(), "")
    principal = auth.session_principal(sid)
    if principal is None:
        raise errors.authentication_error()
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        enforce_origin_headers(request)
    return principal


def enforce_origin_headers(request: Request) -> None:
    """Same-origin check for state-changing session JSON requests."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        parts = urlsplit(origin)
        candidate = f"{parts.scheme}://{parts.netloc}"
        host = request.headers.get("host", "")
        allowed = set()
        if host:
            allowed.add(f"http://{host}")
            allowed.add(f"https://{host}")
        if config.external_origin():
            allowed.add(config.external_origin())
        if candidate not in allowed:
            raise errors.permission_error("cross-origin request rejected",
                                          "cross_origin")
    if not request.headers.get("x-requested-with"):
        raise errors.permission_error("missing X-Requested-With header",
                                      "missing_requested_with")


def require_scope(request: Request, scope: str) -> auth.Principal:
    principal = resolve_principal(request)
    if not principal.has_scope(scope):
        audit.record("permission_denied", actor=principal.username,
                     ip=client_ip(request), reason="scope", target=scope)
        raise errors.permission_error(f"missing scope: {scope}", "missing_scope")
    return principal


# ---------------------------------------------------------------- helpers

def run_idempotent(request: Request, principal: auth.Principal, payload: dict,
                   endpoint: str, handler):
    """Replay-safe execution for POST endpoints."""
    key = request.headers.get("idempotency-key", "").strip()
    if key:
        if len(key) > 255:
            raise errors.invalid_request("Idempotency-Key exceeds 255 characters",
                                         "invalid_idempotency_key", status=422)
        scope = f"{principal.username}:{endpoint}"
        stored = idempotency.lookup(key, scope)
        if stored is not None:
            if stored["request_hash"] != idempotency.request_fingerprint(payload):
                raise errors.idempotency_error(
                    "Idempotency-Key is already bound to different parameters")
            return JSONResponse(
                status_code=stored["status"],
                content=json.loads(stored["body"]),
                headers={"Idempotent-Replay": "true"},
            )
    status, body = handler()
    if key and status < 500:
        idempotency.store(key, f"{principal.username}:{endpoint}",
                          idempotency.request_fingerprint(payload), status,
                          json.dumps(body, ensure_ascii=False))
    return JSONResponse(status_code=status, content=body)


def upstream_guard(call):
    """Translate UpstreamError into the API error envelope."""
    try:
        return call()
    except clients.UpstreamError as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else None
        message = str(detail.get("detail") or exc.args[0]) if detail else exc.args[0]
        status = exc.status if exc.status >= 400 else 502
        error_type = "api_error" if status >= 500 else "invalid_request_error"
        raise errors.ApiError(status, error_type, "upstream_error", message)


def page_after(items: list, cursor_field: str, cursor: str | None) -> list:
    if cursor is None:
        return items
    for index, item in enumerate(items):
        if str(item.get(cursor_field)) == str(cursor):
            return items[index + 1:]
    return []


# ---------------------------------------------------------------- incidents

@router.get("/incidents")
def list_incidents(request: Request, limit: int | None = None,
                   cursor: str | None = None, status: str | None = None) -> JSONResponse:
    require_scope(request, "incidents:read")
    bounded = errors.clamp_limit(limit)
    incidents = upstream_guard(clients.gateway_incidents)
    if status:
        incidents = [item for item in incidents if item.get("status") == status]
    incidents = page_after(incidents, "incident_id", cursor)
    return JSONResponse(errors.envelope(
        incidents, limit=bounded, cursor_of=lambda item: item.get("incident_id")))


@router.get("/incidents/{incident_id}")
def get_incident(request: Request, incident_id: str) -> JSONResponse:
    require_scope(request, "incidents:read")
    detail = upstream_guard(lambda: clients.gateway_incident(incident_id))
    return JSONResponse({"data": detail})


class WorkflowBody(BaseModel):
    state: str = Field(min_length=3, max_length=64)
    message: str = Field(default="", max_length=1024)
    session_id: str | None = Field(default=None, min_length=3, max_length=128)


@router.post("/incidents/{incident_id}/workflow")
def transition_workflow(request: Request, incident_id: str, body: WorkflowBody):
    principal = require_scope(request, "incidents:write")

    def handler():
        result = upstream_guard(lambda: clients.gateway_transition(
            incident_id, body.state, principal.username, body.message,
            body.session_id or "console"))
        audit.record("workflow_transition", actor=principal.username,
                     ip=client_ip(request), target=incident_id, reason=body.state)
        return 200, {"data": result}

    return run_idempotent(request, principal,
                          {"incident_id": incident_id, **body.model_dump()},
                          f"workflow:{incident_id}", handler)


# ---------------------------------------------------------------- proposals

@router.get("/proposals")
def list_proposals(request: Request, status: str | None = None,
                   limit: int | None = None, cursor: str | None = None) -> JSONResponse:
    require_scope(request, "incidents:read")
    bounded = errors.clamp_limit(limit)
    proposals = upstream_guard(clients.executor_pending_proposals)
    wanted = status or "pending_approval"
    proposals = [item for item in proposals if item.get("status") == wanted]
    proposals = page_after(proposals, "action_id", cursor)
    return JSONResponse(errors.envelope(
        proposals, limit=bounded, cursor_of=lambda item: item.get("action_id")))


class DecisionBody(BaseModel):
    action: str = Field(pattern="^(approve|deny)$")
    classification: str = Field(min_length=1)
    comment: str = Field(min_length=4, max_length=4000)
    expires_minutes: int = Field(default=15, ge=1, le=60)


@router.post("/proposals/{action_id}/decision")
def decide(request: Request, action_id: str, body: DecisionBody):
    if body.classification not in DECISION_CLASSIFICATIONS:
        raise errors.invalid_request(
            f"classification must be one of: {', '.join(DECISION_CLASSIFICATIONS)}",
            "invalid_classification", status=422)
    principal = require_scope(request, "decisions:write")

    def handler():
        upstream = None
        incident_id = None
        if body.action == "approve":
            upstream = upstream_guard(lambda: clients.executor_approve(
                action_id, principal.username, body.expires_minutes))
            incident_id = upstream.get("incident_id") if upstream else None
        audit.record_decision(action_id=action_id, incident_id=incident_id,
                              actor=principal.username, action=body.action,
                              classification=body.classification,
                              comment=body.comment,
                              executor_status=200 if upstream else None)
        return 200, {"data": {
            "action_id": action_id, "decision": body.action,
            "classification": body.classification, "actor": principal.username,
            "executor": upstream, "recorded": True,
        }}

    return run_idempotent(request, principal,
                          {"action_id": action_id, **body.model_dump()},
                          f"decision:{action_id}", handler)


# ---------------------------------------------------------------- audit

@router.get("/audit-events")
def list_audit_events(request: Request, limit: int | None = None,
                      cursor: int | None = None, event: str | None = None) -> JSONResponse:
    require_scope(request, "audit:read")
    bounded = errors.clamp_limit(limit)
    items = audit.list_events(before_id=cursor, limit=bounded + 1, event=event)
    return JSONResponse(errors.envelope(
        items, limit=bounded, cursor_of=lambda item: str(item["id"])))


# ---------------------------------------------------------------- keys

class KeyCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(min_length=1, max_length=16)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


@router.get("/keys")
def list_keys(request: Request, limit: int | None = None,
              cursor: int | None = None) -> JSONResponse:
    require_scope(request, "keys:admin")
    bounded = errors.clamp_limit(limit)
    keys = apikeys.list_keys()
    if cursor is not None:
        keys = [item for item in keys if item["id"] < cursor]
    return JSONResponse(errors.envelope(
        keys, limit=bounded, cursor_of=lambda item: str(item["id"])))


@router.post("/keys")
def create_key(request: Request, body: KeyCreateBody):
    principal = require_scope(request, "keys:admin")

    def handler():
        try:
            expires_at = apikeys.expiry_from_days(body.expires_in_days)
            key_id, plaintext, meta = apikeys.create_key(
                name=body.name, scopes=body.scopes,
                created_by=principal.username, expires_at=expires_at)
        except ValueError as exc:
            raise errors.invalid_request(str(exc), "invalid_scopes", status=422) from None
        return 201, {"data": {**meta, "id": key_id, "secret": plaintext}}

    return run_idempotent(request, principal, body.model_dump(), "key_create", handler)


@router.delete("/keys/{key_id}")
def revoke_key(request: Request, key_id: int):
    principal = require_scope(request, "keys:admin")
    if not apikeys.revoke_key(key_id, principal.username):
        raise errors.invalid_request("key not found or already revoked",
                                     "unknown_key", status=404)
    return JSONResponse({"data": {"id": key_id, "revoked": True}})


# ---------------------------------------------------------------- usage

@router.get("/usage/summary")
def usage(request: Request) -> JSONResponse:
    require_scope(request, "usage:read")
    return JSONResponse({"data": clients.usage_summary()})
