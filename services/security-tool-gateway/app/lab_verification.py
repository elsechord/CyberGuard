"""Read-only account probes; executor receipts authorize attribution, not success."""
import json
import os
from http.client import HTTPException
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4


class ProbeError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def origin(name):
    value = os.getenv(name, "")
    p = urlsplit(value)
    if (p.scheme != "http" or p.hostname != "127.0.0.1" or not p.port
            or p.username or p.password or p.path not in {"", "/"} or p.query or p.fragment):
        raise ProbeError("lab probes require configured loopback origins")
    return value.rstrip("/")


def read(url, token, allowed_status=(200,)):
    if not token:
        raise ProbeError("missing read credential")
    req = Request(url, headers={"Authorization": "Bearer " + token, "Cache-Control": "no-cache"})
    try:
        try:
            response = build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=3)
        except HTTPError as exc:
            if exc.code not in allowed_status:
                raise ProbeError("probe or audit endpoint unavailable") from None
            response = exc
        with response:
            status = response.code
            raw = response.read(65537)
        if status not in allowed_status or len(raw) > 65536:
            raise ProbeError("invalid probe response")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ProbeError("invalid probe body")
        return status, payload
    except (URLError, OSError, ValueError, HTTPException):
        raise ProbeError("probe unavailable or malformed") from None


def probe(account, token_env, environment_id):
    nonce = uuid4().hex
    status, result = read(origin("CYBERGUARD_LAB_URL") + "/access?nonce=" + nonce,
                          os.getenv(token_env, ""), (200, 403))
    expected = {"account": account, "environment_id": environment_id, "nonce": nonce,
                "allowed": status == 200,
                "reason": "account_enabled" if status == 200 else "account_disabled"}
    if any(result.get(k) != v for k, v in expected.items()) or type(result.get("allowed")) is not bool:
        raise ProbeError("probe identity, freshness or response mismatch")
    return {**result, "http_status": status, "observed_at": datetime.now(UTC).isoformat()}


def verify(incident_id, arguments):
    run_id, action_id = arguments.get("run_id"), arguments.get("action_id")
    if not all(isinstance(v, str) and 3 <= len(v) <= 128 for v in (run_id, action_id)):
        raise ProbeError("run_id and action_id are required")
    data = {"run_id": run_id, "action_id": action_id, "environment": "lab", "execution": "real",
            "verdict": "inconclusive", "telemetry_health": "unknown", "checks": []}
    try:
        _, audit = read(origin("CYBERGUARD_AUDIT_VERIFY_URL") + "/audit/incidents/" +
                        quote(incident_id, safe="") + "/active", os.getenv("CYBERGUARD_AUDIT_READER_TOKEN", ""))
        matches = [a for a in audit.get("active_actions", []) if isinstance(a, dict)
                   and a.get("action_id") == action_id and a.get("run_id") == run_id
                   and a.get("action") == "disable_account" and a.get("target") == "compromised-lab"
                   and a.get("execution_mode") == "lab" and a.get("environment_id")]
        if len(matches) != 1:
            raise ProbeError("no matching active lab action for this run")
        environment_id = matches[0]["environment_id"]
        data["environment_id"] = environment_id
        # These are requests to the actual identity service, not audit-derived
        # booleans. Preserve a partial observation if the other probe fails.
        target = probe("compromised-lab", "CYBERGUARD_LAB_TARGET_TOKEN", environment_id)
        data["checks"].append(target)
        control = probe("control-lab", "CYBERGUARD_LAB_CONTROL_TOKEN", environment_id)
        data["checks"].append(control)
        data.update(telemetry_health="healthy", verdict="verified" if not target["allowed"]
                    and control["allowed"] else "failed", reason="fresh_account_access_probes",
                    audit_head=audit.get("audit_head"), verification_scope="point_in_time_lab_access")
    except (ProbeError, ValueError, TypeError):
        data["reason"] = "probe_unavailable_or_action_binding_invalid"
    return {"source": "lab-account-probe", "kind": "recovery_metrics",
            "observed_at": datetime.now(UTC).isoformat(), "confidence": 1.0,
            "summary": "Point-in-time lab account access check; not a production recovery claim.",
            "handling": "internal", "data": data}
