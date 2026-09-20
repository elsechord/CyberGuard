"""HTML pages: login/setup, overview, incident queue and detail, approvals,
guard ledger, audit trail and admin settings. Session forms carry a per-session
synchronizer CSRF token; the login form uses a short-lived signed token issued
before any session exists.
"""
import base64
import csv
import hashlib
import hmac
import io
import secrets
import time
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from . import apikeys, audit, auth, clients, config, connect, db, jobs
from .api import DECISION_CLASSIFICATIONS, client_ip
from .render import render

router = APIRouter(include_in_schema=False)

LOGIN_CSRF_TTL = 900
_LOGIN_SECRET = secrets.token_bytes(32)  # per-process; restart invalidates
WORKFLOW_STATES = ["received", "investigating", "evidence_validation",
                   "awaiting_approval", "approved", "executing", "completed",
                   "rejected", "failed", "timed_out"]
STATUS_TABS = ["", "investigating", "awaiting_approval", "responding",
               "rolled_back", "verified"]


# ---------------------------------------------------------------- csrf

def login_csrf_token() -> str:
    expires = str(int(time.time()) + LOGIN_CSRF_TTL).encode()
    payload = base64.urlsafe_b64encode(expires).decode().rstrip("=")
    signature = hmac.new(_LOGIN_SECRET, b"login-csrf:" + payload.encode(),
                         hashlib.sha256).hexdigest()
    return payload + "." + signature


def login_csrf_valid(token: str) -> bool:
    if not token or "." not in token:
        return False
    payload, signature = token.rsplit(".", 1)
    expected = hmac.new(_LOGIN_SECRET, b"login-csrf:" + payload.encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        padded = payload + "=" * (-len(payload) % 4)
        expires = int(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return False
    return expires >= time.time()


async def form_of(request: Request) -> dict:
    """Parse application/x-www-form-urlencoded bodies without python-multipart.

    The console never accepts file uploads, so a plain urlencoded parser is
    sufficient and keeps the dependency surface minimal.
    """
    raw = await request.body()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    return {key: values[-1] for key, values in
            parse_qs(text, keep_blank_values=True).items()}


def check_csrf(principal: auth.Principal, form: dict) -> None:
    if not hmac.compare_digest(form.get("csrf_token") or "", principal.csrf or ""):
        raise HTTPException(status_code=403, detail="invalid CSRF token")


def set_session_cookie(response: Response, sid: str) -> None:
    response.set_cookie(config.cookie_name(), sid, httponly=True,
                        secure=config.cookie_secure(), samesite=config.cookie_samesite(), path="/")


# ---------------------------------------------------------------- login/logout

def demo_login_context() -> dict:
    username = config.public_demo_username()
    password = config.public_demo_password()
    user = auth.get_user(username) if username and password else None
    if user is None or user["role"] != "admin" or user["disabled"]:
        return {"demo_username": "", "demo_password": ""}
    return {"demo_username": username, "demo_password": password}

@router.get("/login")
async def login_page(request: Request):
    if auth.user_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    if auth.session_principal(request.cookies.get(config.cookie_name(), "")):
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", csrf=login_csrf_token(),
                  error=None, notice=request.query_params.get("notice"),
                  **demo_login_context())


@router.post("/login")
async def login_submit(request: Request):
    form = await form_of(request)
    if not login_csrf_valid(form.get("login_csrf") or ""):
        return render(request, "login.html", csrf=login_csrf_token(),
                      error="会话已过期，请重新提交。", notice=None, status_code=403,
                      **demo_login_context())
    outcome = await run_in_threadpool(
        auth.attempt_login, form.get("username") or "", form.get("password") or "",
        ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    if not outcome.ok:
        message = (auth.UNIFIED_LOGIN_MESSAGE if outcome.reason == "invalid_credentials"
                   else "账户已锁定，请 15 分钟后重试。")
        status = 401 if outcome.reason == "invalid_credentials" else 429
        return render(request, "login.html", csrf=login_csrf_token(),
                      error=message, notice=None, status_code=status,
                      **demo_login_context())
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, outcome.sid)
    return response


@router.post("/logout")
async def logout(request: Request):
    sid = request.cookies.get(config.cookie_name(), "")
    principal = auth.session_principal(sid)
    if principal:
        check_csrf(principal, await form_of(request))
        auth.drop_session(sid)
        audit.record("logout", actor=principal.username, ip=client_ip(request),
                     session_id=sid)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(config.cookie_name(), path="/")
    return response


# ---------------------------------------------------------------- setup

def _masked(token: str) -> str:
    if len(token) <= 8:
        return "••••"
    return token[:4] + "••••" + token[-4:]


@router.get("/setup")
async def setup_page(request: Request):
    state = auth.setup_state()
    if not state["open"]:
        return RedirectResponse("/login", status_code=303)
    return render(request, "setup.html", masked=_masked(state["token"] or ""),
                  csrf=login_csrf_token(), error=None,
                  notice=request.query_params.get("notice"))


@router.post("/setup")
async def setup_submit(request: Request):
    state = auth.setup_state()
    if not state["open"]:
        return RedirectResponse("/login", status_code=303)
    form = await form_of(request)
    error = None
    if not login_csrf_valid(form.get("login_csrf") or ""):
        error = "会话已过期，请重新提交。"
    elif not hmac.compare_digest(form.get("setup_token") or "",
                                 state["token"] or ""):
        audit.record("setup", result="failure", reason="invalid_setup_token",
                     ip=client_ip(request))
        error = "Setup token 不正确；请从服务启动日志中复制。"
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    confirm = form.get("password_confirm") or ""
    if error is None:
        if not 3 <= len(username) <= 64:
            error = "用户名长度需在 3-64 之间。"
        elif len(password) < 12:
            error = "管理员密码至少 12 个字符。"
        elif password != confirm:
            error = "两次输入的密码不一致。"
    if error is not None:
        return render(request, "setup.html", masked=_masked(state["token"] or ""),
                      csrf=login_csrf_token(), error=error, notice=None,
                      status_code=422)
    auth.create_user(username, password, "admin")
    jobs.init_db()
    auth.finish_setup()
    auth.ensure_public_demo_admin()
    audit.record("setup", actor=username, result="success",
                 ip=client_ip(request), reason="admin_created")
    outcome = await run_in_threadpool(auth.attempt_login, username, password,
                                      ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    response = RedirectResponse("/settings/onboarding" if outcome.ok else "/login?notice=admin-created", status_code=303)
    if outcome.ok:
        set_session_cookie(response, outcome.sid)
    return response



def page_session(request: Request) -> auth.Principal:
    """Pages redirect anonymous browsers to /login; API keeps 401 semantics."""
    try:
        return auth.require_session(request)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise HTTPException(status_code=303, headers={"Location": "/login"}) from None
        raise

# ---------------------------------------------------------------- overview

@router.get("/")
def overview(request: Request):
    principal = page_session(request)
    from .investigation_pages import STATUSES, stage_label
    active_jobs = jobs.list_active_jobs(principal)
    incidents = _safe(lambda: clients.gateway_incidents(), [])
    open_count = sum(1 for item in incidents
                     if item.get("status") not in {"completed", "rejected", "verified"})
    evidence_total = sum(int(item.get("evidence_count") or 0) for item in incidents)
    pending = _safe(lambda: len(clients.executor_pending_proposals()), 0)
    usage = _safe(clients.usage_summary, {"available": False})
    return render(request, "overview.html", principal=None,
                  incidents=incidents[:10], open_count=open_count,
                  pending_count=pending, evidence_total=evidence_total,
                  usage=usage, upstream_ok=bool(config.gateway_url()),
                  active_jobs=active_jobs, statuses=STATUSES, stage_label=stage_label)


def _safe(call, fallback):
    try:
        return call()
    except clients.UpstreamError:
        return fallback


# ---------------------------------------------------------------- incidents

@router.get("/incidents")
def incidents_page(request: Request, status: str | None = None):
    principal = page_session(request)
    from .investigation_pages import STATUSES, stage_label
    incidents = _safe(lambda: clients.gateway_incidents(), None)
    if incidents is not None and status:
        incidents = [item for item in incidents if item.get("status") == status]
    return render(request, "incidents.html", principal=None,
                  incidents=incidents, active_status=status or "",
                  tabs=STATUS_TABS, upstream_ok=incidents is not None,
                  active_jobs=jobs.list_active_jobs(principal),
                  statuses=STATUSES, stage_label=stage_label)


@router.get("/incidents/fragment")
def incidents_fragment(request: Request, status: str | None = None):
    page_session(request)
    incidents = _safe(lambda: clients.gateway_incidents(), [])
    if status:
        incidents = [item for item in incidents if item.get("status") == status]
    return render(request, "_queue_fragment.html", incidents=incidents,
                  active_status=status or "")


@router.get("/incidents/{incident_id}")
def incident_detail(request: Request, incident_id: str):
    principal = page_session(request)
    try:
        detail = clients.gateway_incident(incident_id)
    except clients.UpstreamError as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404, detail="incident not found") from None
        detail = None
    timeline = []
    wf_state = ""
    actions_view = []
    if detail:
        wf_events = (detail.get("workflow") or {}).get("events") or []
        if wf_events:
            latest = max(wf_events, key=lambda event: event.get("recorded_at") or "")
            wf_state = latest.get("state") or ""
        for event in wf_events:
            timeline.append({"ts": event.get("recorded_at"), "kind": "workflow",
                             "text": f'{event.get("state")} — {event.get("actor")}: '
                                     f'{event.get("message") or "(无备注)"}'})
        for item in detail.get("evidence", []):
            timeline.append({"ts": item.get("collected_at"), "kind": "evidence",
                             "text": f'{item.get("source")} · {item.get("kind")} — '
                                     f'{item.get("summary")}'})
        latest_actions: dict[str, dict] = {}
        action_names: dict[str, str] = {}
        for action in detail.get("actions", []):
            action_id = action.get("action_id")
            if not action_id:
                continue
            # audit file is append-ordered; merge so latest non-null field wins
            merged = {**latest_actions.get(action_id, {}),
                      **{k: v for k, v in action.items() if v is not None}}
            latest_actions[action_id] = merged
            if merged.get("action"):
                action_names[action_id] = merged["action"]
            if action.get("status"):
                timeline.append({"ts": action.get("recorded_at"), "kind": "action",
                                 "text": f'{action_id} · '
                                         f'{action_names.get(action_id) or "?"}'
                                         f' → {action.get("status")}'})
        actions_view = list(latest_actions.values())
    rows = db.connection().execute(
        "SELECT * FROM comment WHERE incident_id = ? ORDER BY id DESC", (incident_id,)
    ).fetchall()
    for row in rows:
        timeline.append({"ts": row["created_at"], "kind": "comment",
                         "text": f'{row["author"]}: {row["body"]}'})
    timeline = [item for item in timeline if item.get("ts")]
    timeline.sort(key=lambda item: item["ts"], reverse=True)
    return render(request, "incident.html", principal=principal,
                  incident_id=incident_id, detail=detail, timeline=timeline,
                  wf_state=wf_state, actions_view=actions_view,
                  workflow_states=WORKFLOW_STATES)


@router.post("/incidents/{incident_id}/workflow")
async def workflow_submit(request: Request, incident_id: str):
    principal = page_session(request)
    if not principal.has_role("analyst"):
        raise HTTPException(status_code=403, detail="insufficient role")
    form = await form_of(request)
    check_csrf(principal, form)
    state = form.get("state") or ""
    message = (form.get("message") or "")[:1024]
    if state not in WORKFLOW_STATES:
        raise HTTPException(status_code=422, detail="invalid state")
    try:
        session_id = await run_in_threadpool(clients.gateway_latest_session, incident_id)
        await run_in_threadpool(clients.gateway_transition, incident_id, state,
                                principal.username, message,
                                session_id or "console")
    except clients.UpstreamError:
        return RedirectResponse(f"/incidents/{incident_id}?notice=workflow-failed",
                                status_code=303)
    audit.record("workflow_transition", actor=principal.username,
                 ip=client_ip(request), target=incident_id, reason=state)
    return RedirectResponse(f"/incidents/{incident_id}?notice=workflow-ok",
                            status_code=303)


@router.post("/incidents/{incident_id}/comments")
async def comment_submit(request: Request, incident_id: str):
    principal = page_session(request)
    if not principal.has_role("analyst"):
        raise HTTPException(status_code=403, detail="insufficient role")
    form = await form_of(request)
    check_csrf(principal, form)
    body = (form.get("body") or "").strip()
    if 1 <= len(body) <= 4000:
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO comment (org_id, incident_id, author, body, created_at) "
                "VALUES ('default', ?, ?, ?, ?)",
                (incident_id, principal.username, body, audit.now_iso()))
    return RedirectResponse(f"/incidents/{incident_id}?notice=comment-ok",
                            status_code=303)


# ---------------------------------------------------------------- approvals

@router.get("/approvals")
def approvals_page(request: Request):
    principal = page_session(request)
    proposals = _safe(lambda: clients.executor_pending_proposals(), [])
    enriched = []
    for proposal in proposals:
        item = dict(proposal)
        item["decisions"] = [dict(row) for row in db.connection().execute(
            "SELECT * FROM decision WHERE action_id = ? ORDER BY id DESC",
            (proposal.get("action_id"),)).fetchall()]
        enriched.append(item)
    return render(request, "approvals.html", principal=principal,
                  proposals=enriched,
                  classifications=DECISION_CLASSIFICATIONS)


@router.post("/approvals/{action_id}/decision")
async def decision_submit(request: Request, action_id: str):
    principal = page_session(request)
    if not principal.has_role("approver"):
        raise HTTPException(status_code=403, detail="insufficient role")
    form = await form_of(request)
    check_csrf(principal, form)
    action = form.get("action") or ""
    classification = form.get("classification") or ""
    comment = (form.get("comment") or "").strip()
    if action not in {"approve", "deny"}:
        raise HTTPException(status_code=422, detail="invalid action")
    if classification not in DECISION_CLASSIFICATIONS:
        raise HTTPException(status_code=422, detail="classification is required")
    if len(comment) < 4:
        raise HTTPException(status_code=422, detail="comment is required")
    upstream = None
    if action == "approve":
        try:
            upstream = await run_in_threadpool(clients.executor_approve, action_id,
                                               principal.username)
        except clients.UpstreamError:
            return RedirectResponse("/approvals?notice=upstream-failed",
                                    status_code=303)
    incident_id = None
    try:
        incident_id = await run_in_threadpool(clients.executor_incident_for_action,
                                              action_id)
    except clients.UpstreamError:
        incident_id = None
    if incident_id:
        try:
            await run_in_threadpool(clients.advance_after_decision, incident_id,
                                    action, principal.username,
                                    f"{classification}: {comment}")
        except clients.UpstreamError:
            pass
    audit.record_decision(action_id=action_id, incident_id=incident_id,
                          actor=principal.username, action=action,
                          classification=classification, comment=comment,
                          executor_status=200 if upstream else None)
    return RedirectResponse("/approvals?notice=decision-recorded", status_code=303)


# ---------------------------------------------------------------- ledger

@router.get("/ledger")
def ledger_page(request: Request):
    page_session(request)
    usage = clients.usage_summary()
    return render(request, "ledger.html", principal=None, usage=usage)


# ---------------------------------------------------------------- audit

@router.get("/audit")
def audit_page(request: Request, limit: int = 50):
    principal = auth.require("admin")(request)
    events = audit.list_events(limit=min(limit, 200))
    return render(request, "audit.html", principal=principal, events=events)


@router.get("/audit/export.csv")
def audit_export(request: Request):
    principal = auth.require("admin")(request)
    events = audit.export_events()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "ts", "event", "actor", "result", "reason", "ip",
                     "user_agent", "target", "session_hash", "request_id"])
    for item in events:
        writer.writerow([item.get(field) for field in
                         ("id", "ts", "event", "actor", "result", "reason", "ip",
                          "user_agent", "target", "session_hash", "request_id")])
    audit.record("audit_export", actor=principal.username,
                 ip=client_ip(request), reason=f"{len(events)} rows")
    return PlainTextResponse(buffer.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition":
                                      'attachment; filename="cyberguard-audit.csv"'})


# ---------------------------------------------------------------- settings

def connection_page(request: Request, principal, values: dict, *, issue_key=False):
    agent = values.get("agent") or "codex"
    incident_id = values.get("incident_id") or ""
    key_file = (values.get("key_file") or "").strip()
    purpose = values.get("purpose") or "investigations"
    incidents = _safe(clients.gateway_incidents, None)
    origin, prompt, error, new_secret = "", "", None, None
    try:
        origin = connect.public_origin(request, config.external_origin())
        if purpose == "read" and incident_id and (incidents is None or not any(
                item.get("incident_id") == incident_id for item in incidents)):
            raise ValueError("所选事件当前不可用；请刷新事件列表，或只验证连接。")
        prompt = connect.build_prompt(origin, agent, key_file, incident_id, purpose)
        if issue_key:
            _, new_secret, _ = apikeys.create_key(
                name=f"agent-{agent}-{principal.username}"[:128],
                scopes=(["investigations:read", "investigations:write"] if purpose == "investigations" else ["incidents:read"]), created_by=principal.username,
                expires_at=apikeys.expiry_from_days(30))
    except ValueError as exc:
        error = str(exc)
    return render(request, "connect.html", principal=principal, agents=connect.AGENTS,
                  agent=agent, incident_id=incident_id, key_file=key_file, purpose=purpose,
                  origin=origin, prompt=prompt, error=error, incidents=incidents,
                  new_secret=new_secret, status_code=422 if error and request.method == "POST" else 200)


@router.get("/connect")
def connect_page(request: Request):
    principal = page_session(request)
    return connection_page(request, principal, dict(request.query_params))


@router.post("/connect/prompt")
async def connect_prompt(request: Request):
    principal = page_session(request)
    form = await form_of(request)
    check_csrf(principal, form)
    return await run_in_threadpool(connection_page, request, principal, form)


@router.post("/connect/key")
async def connect_key(request: Request):
    principal = auth.require("admin")(request)
    form = await form_of(request)
    check_csrf(principal, form)
    return await run_in_threadpool(connection_page, request, principal, form, issue_key=True)

@router.get("/settings/members")
def members_page(request: Request):
    principal = auth.require("admin")(request)
    return render(request, "members.html", principal=principal,
                  users=auth.list_users(), roles=list(auth.ROLE_RANK),
                  error=request.query_params.get("error"))


@router.post("/settings/members")
async def members_create(request: Request):
    principal = auth.require("admin")(request)
    form = await form_of(request)
    check_csrf(principal, form)
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    role = form.get("role") or "viewer"
    if len(password) < 12:
        return RedirectResponse("/settings/members?error=weak-password",
                                status_code=303)
    try:
        auth.create_user(username, password, role)
    except ValueError:
        return RedirectResponse("/settings/members?error=invalid-username",
                                status_code=303)
    audit.record("member_created", actor=principal.username, target=username,
                 reason=role, ip=client_ip(request))
    return RedirectResponse("/settings/members?notice=member-created", status_code=303)


@router.post("/settings/members/{user_id}/role")
async def members_role(request: Request, user_id: int):
    principal = auth.require("admin")(request)
    form = await form_of(request)
    check_csrf(principal, form)
    role = form.get("role") or ""
    target = auth.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if target["id"] == principal.user_id and role != "admin":
        raise HTTPException(status_code=422, detail="admins cannot demote themselves")
    auth.set_user_role(user_id, role)  # rotates the target's sessions
    audit.record("member_role_changed", actor=principal.username,
                 target=target["username"], reason=role, ip=client_ip(request))
    return RedirectResponse("/settings/members?notice=role-updated", status_code=303)


@router.post("/settings/members/{user_id}/disable")
async def members_disable(request: Request, user_id: int):
    principal = auth.require("admin")(request)
    form = await form_of(request)
    check_csrf(principal, form)
    disable = form.get("disabled") == "1"
    target = auth.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if target["id"] == principal.user_id and disable:
        raise HTTPException(status_code=422, detail="admins cannot disable themselves")
    auth.set_user_disabled(user_id, disable)
    audit.record("member_disabled" if disable else "member_enabled",
                 actor=principal.username, target=target["username"],
                 ip=client_ip(request))
    return RedirectResponse("/settings/members?notice=member-updated", status_code=303)


@router.get("/settings/keys")
def keys_page(request: Request):
    principal = auth.require("admin")(request)
    return render(request, "keys.html", principal=principal, keys=apikeys.list_keys(),
                  scopes=apikeys.auth_all_scopes(), new_secret=None,
                  notice=request.query_params.get("notice"))


@router.post("/settings/keys")
async def keys_create(request: Request):
    principal = auth.require("admin")(request)
    form = await form_of(request)
    check_csrf(principal, form)
    scopes = [scope for scope in (form.get("scopes") or "").split(",") if scope]
    expires_days = int(form["expires_in_days"]) if form.get("expires_in_days") else None
    try:
        key_id, plaintext, meta = apikeys.create_key(
            name=(form.get("name") or "unnamed")[:128], scopes=scopes,
            created_by=principal.username,
            expires_at=apikeys.expiry_from_days(expires_days))
    except (ValueError, TypeError):
        return RedirectResponse("/settings/keys?notice=invalid-scopes", status_code=303)
    return render(request, "keys.html", principal=principal,
                  keys=apikeys.list_keys(), scopes=apikeys.auth_all_scopes(),
                  new_secret=plaintext, new_key=meta, notice=None)


@router.post("/settings/keys/{key_id}/revoke")
async def keys_revoke(request: Request, key_id: int):
    principal = auth.require("admin")(request)
    form = await form_of(request)
    check_csrf(principal, form)
    apikeys.revoke_key(key_id, principal.username)
    return RedirectResponse("/settings/keys?notice=key-revoked", status_code=303)


# ---------------------------------------------------------------- health

@router.get("/healthz")
def healthz() -> dict:
    try:
        db.connection().execute("SELECT 1").fetchone()
        return {"status": "ok", "service": "operations-console"}
    except Exception:  # noqa: BLE001 - health probe must never raise
        return {"status": "degraded", "service": "operations-console"}
