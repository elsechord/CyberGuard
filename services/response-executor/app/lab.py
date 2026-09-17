"""A deliberately narrow adapter to CyberGuard's loopback identity laboratory."""
import json
import os
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class BackendError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def mode():
    value = os.getenv("CYBERGUARD_EXECUTION_MODE", "simulation")
    if value not in {"simulation", "lab", "host_lab"}:
        raise BackendError("unsupported execution mode; expected simulation, lab or host_lab")
    return value


def base_url():
    url = os.getenv("CYBERGUARD_HOST_LAB_URL" if mode() == "host_lab" else "CYBERGUARD_LAB_URL", "")
    parts = urlsplit(url)
    if (parts.scheme != "http" or parts.hostname != "127.0.0.1" or not parts.port
            or parts.username or parts.password or parts.path not in {"", "/"}
            or parts.query or parts.fragment):
        raise BackendError("lab URL must be an explicit http://127.0.0.1:port origin")
    return url.rstrip("/")


def request(path, body=None, *, missing_ok=False):
    token = os.getenv("CYBERGUARD_HOST_ADMIN_TOKEN" if mode() == "host_lab" else "CYBERGUARD_LAB_ADMIN_TOKEN", "")
    if len(token) < 32:
        raise BackendError("lab admin token is not configured")
    req = Request(base_url() + path, data=json.dumps(body).encode() if body is not None else None,
                  headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=3) as response:
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError("oversized receipt")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("invalid receipt")
        return result
    except HTTPError as exc:
        if missing_ok and exc.code == 404:
            return None
        raise BackendError("lab request failed; outcome must be reconciled") from None
    except (URLError, TimeoutError, OSError, ValueError, HTTPException):
        raise BackendError("lab unavailable or returned an invalid receipt") from None


def binding():
    result = request("/health")
    if result.get("environment") != "lab" or not isinstance(result.get("environment_id"), str):
        raise BackendError("invalid lab environment")
    if mode() == "host_lab" and result.get("backend") != "host_lab":
        raise BackendError("host lab backend required")
    return {"backend_url": base_url(), "environment_id": result["environment_id"]}


def operation(proposal, rollback=False):
    if proposal.get("execution_mode") == "host_lab" and rollback:
        raise BackendError("process laboratory actions cannot be rolled back")
    kind = proposal["action"] if proposal.get("execution_mode") == "host_lab" else "restore" if rollback else "disable"
    return {"kind": kind, "target": proposal["target"],
            "action_id": proposal["action_id"], "run_id": proposal["run_id"],
            "environment_id": proposal["environment_id"]}


def check_binding(proposal):
    if mode() not in {"lab", "host_lab"} or mode() != proposal.get("execution_mode", "lab") or base_url() != proposal["backend_url"]:
        raise BackendError("execution backend differs from the approved proposal")


def apply(proposal, rollback=False):
    check_binding(proposal)
    op_id = proposal["action_id"] + ("-rollback" if rollback else "")
    receipt = request("/operations/" + op_id, operation(proposal, rollback))
    validate_receipt(proposal, receipt, rollback)
    return receipt


def reconcile(proposal, rollback=False):
    check_binding(proposal)
    op_id = proposal["action_id"] + ("-rollback" if rollback else "")
    receipt = request("/operations/" + op_id, missing_ok=True)
    if receipt is not None:
        validate_receipt(proposal, receipt, rollback)
    return receipt


def validate_receipt(proposal, receipt, rollback):
    expected = operation(proposal, rollback)
    allowed = {"applied", "rejected"} if proposal.get("execution_mode") == "host_lab" else {"applied"}
    if receipt.get("result") not in allowed:
        raise BackendError("backend outcome remains unresolved")
    expected.update(operation_id=proposal["action_id"] + ("-rollback" if rollback else ""))
    if any(receipt.get(k) != v for k, v in expected.items()):
        raise BackendError("receipt does not match this run, target and operation")
