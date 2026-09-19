"""Outbound HTTP to the gateway, executor and model guard.

Follows the repository's established inter-service pattern (see
services/response-executor/app/lab.py): standard library urllib with proxies
explicitly disabled, redirects refused, hard timeouts and bounded response
bodies. Endpoints using these helpers are plain `def` routes, so the blocking
calls run inside Starlette's worker thread pool. Tokens are never logged.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from . import config

MAX_BODY_BYTES = 4 * 1024 * 1024


class UpstreamError(RuntimeError):
    """Raised for transport failures (mapped to 502) and upstream errors."""

    def __init__(self, message: str, *, status: int = 502, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def _fetch(base_url: str, path: str, *, token: str = "", secret: str = "",
           body: dict | None = None, method: str = "GET") -> dict:
    if not base_url:
        raise UpstreamError("upstream service is not configured", status=503)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if secret:
        headers["X-Approval-Secret"] = secret
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=config.upstream_timeout()) as response:
            raw = response.read(MAX_BODY_BYTES + 1)
        if len(raw) > MAX_BODY_BYTES:
            raise UpstreamError("upstream response exceeds size limit")
        if not raw:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise UpstreamError("upstream returned a non-object payload")
        return payload
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read(65537) or b"null")
        except (ValueError, OSError):
            detail = None
        raise UpstreamError("upstream request failed", status=exc.code, detail=detail) from None
    except UpstreamError:
        raise
    except (URLError, TimeoutError, OSError, ValueError):
        raise UpstreamError("upstream unavailable or returned an invalid payload") from None


# ------------------------------------------------------------------ gateway

def gateway_incidents() -> list[dict]:
    payload = _fetch(config.gateway_url(), "/incidents", token=config.gateway_token())
    incidents = payload.get("incidents")
    if not isinstance(incidents, list):
        raise UpstreamError("gateway returned an invalid incident list")
    return incidents


def gateway_incident(incident_id: str) -> dict:
    try:
        return _fetch(config.gateway_url(), f"/incidents/{incident_id}",
                      token=config.gateway_token())
    except UpstreamError as exc:
        if exc.status == 404:
            raise
        raise


def gateway_workflow(incident_id: str, session_id: str = "console") -> dict | None:
    try:
        return _fetch(config.gateway_url(), f"/incidents/{incident_id}/workflow",
                      token=config.gateway_token())
    except UpstreamError as exc:
        if exc.status == 404:
            return None
        raise


def gateway_transition(incident_id: str, state: str, actor: str, message: str,
                       session_id: str = "console") -> dict:
    return _fetch(
        config.gateway_url(), f"/incidents/{incident_id}/workflow",
        token=config.gateway_token(),
        body={"session_id": session_id, "state": state, "actor": actor, "message": message},
    )


# ------------------------------------------------------------------ executor

def executor_action(action_id: str) -> dict:
    return _fetch(config.executor_url(), f"/actions/{action_id}",
                  token=config.executor_token())


def executor_approve(action_id: str, approver: str,
                     expires_minutes: int = 15) -> dict:
    return _fetch(
        config.executor_url(), "/actions/approve",
        token=config.executor_token(), secret=config.executor_approval_secret(),
        body={"action_id": action_id, "approver": approver,
              "expires_minutes": expires_minutes},
    )


def executor_pending_proposals() -> list[dict]:
    """Pending proposals are derived from gateway incident action audits."""
    proposals = []
    for summary in gateway_incidents():
        detail = gateway_incident(summary.get("incident_id", ""))
        for action in detail.get("actions", []):
            if action.get("status") == "pending_approval":
                item = dict(action)
                item["incident_status"] = detail.get("summary", {}).get("status")
                proposals.append(item)
    return proposals


# ------------------------------------------------------------------ model guard

def guard_status() -> dict:
    """Degrades gracefully: any failure maps to {"available": false}."""
    try:
        payload = _fetch(config.guard_url(), "/admin/status",
                         token=config.guard_admin_token())
    except UpstreamError:
        return {"available": False}
    if not isinstance(payload.get("run"), dict):
        return {"available": False, "run": payload.get("run")}
    return {"available": True, **payload}


def usage_summary() -> dict:
    status = guard_status()
    if not status.get("available"):
        return {"available": False}
    run = status.get("run", {})
    return {
        "available": True,
        "run_id": run.get("run_id"),
        "model": run.get("model"),
        "armed": status.get("armed"),
        "run_status": run.get("status"),
        "budgets": {"limits": run.get("limits"), "remaining": run.get("remaining")},
        "consumption": run.get("usage"),
        "requests_by_role": run.get("requests_by_role"),
        "roles": run.get("roles"),
    }
