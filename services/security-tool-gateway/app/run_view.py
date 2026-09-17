"""Run-scoped evidence export. Verdicts are observations, not new recovery probes."""
import hashlib
import json
import os
from datetime import UTC, datetime
from http.client import HTTPException
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def audit_snapshot(incident_id, run_id):
    origin = os.getenv("CYBERGUARD_AUDIT_VERIFY_URL", "").rstrip("/")
    token = os.getenv("CYBERGUARD_AUDIT_READER_TOKEN", "")
    parsed = urlsplit(origin)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment or not token):
        raise ValueError("audit endpoint is not configured")
    req = Request(origin + "/audit/incidents/" + quote(incident_id, safe="") + "/events?" +
                  urlencode({"run_id": run_id}), headers={"Authorization": "Bearer " + token})
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=3) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("audit snapshot exceeds limit")
    snapshot = json.loads(raw)
    if (snapshot.get("incident_id") != incident_id or snapshot.get("run_id") != run_id
            or snapshot.get("audit", {}).get("valid") is not True
            or snapshot.get("audit", {}).get("authenticated") is not True
            or not isinstance(snapshot.get("events"), list)):
        raise ValueError("invalid audit snapshot")
    events = snapshot["events"]
    if any(not isinstance(e, dict) or e.get("incident_id") != incident_id for e in events):
        raise ValueError("invalid audit event")
    proposals = {e["action_id"] for e in events if e.get("status") == "pending_approval"
                 and e.get("run_id") == run_id}
    if any(e.get("action_id") not in proposals or e.get("run_id") not in {None, run_id} for e in events):
        raise ValueError("cross-run audit event")
    return snapshot


def build(incident_id, run_id, evidence):
    result = {"schema": "cyberguard-run-export", "schema_version": "1.0",
              "incident_id": incident_id, "run_id": run_id,
              "exported_at": datetime.now(UTC).isoformat(), "audit_status": "unavailable",
              "actions": [], "evidence": evidence, "action_states": [], "warnings": [],
              "provenance": {"agentteams_task": "not_attested", "worker_skill_binding": "not_attested",
                             "model_mode_source": "caller_reported"}}
    valid_evidence = []
    for e in evidence:
        if (e.get("incident_id") != incident_id or e.get("run_id") != run_id
                or not e.get("envelope_sha256")
                or digest({k: v for k, v in e.items() if k != "envelope_sha256"}) != e["envelope_sha256"]):
            result["warnings"].append("evidence_envelope_invalid:" + str(e.get("evidence_id")))
        else:
            valid_evidence.append(e)
    result["evidence_integrity"] = "valid" if len(valid_evidence) == len(evidence) else "invalid"
    try:
        snapshot = audit_snapshot(incident_id, run_id)
        result.update(actions=snapshot["events"], audit=snapshot["audit"], audit_status="valid",
                      audit_snapshot_at=snapshot["snapshot_at"], audit_assurance="executor_validated_snapshot")
    except (URLError, OSError, ValueError, TypeError, KeyError, HTTPException):
        result["warnings"].append("authenticated_audit_unavailable")
    proposals = [e for e in result["actions"] if e.get("status") == "pending_approval"]
    for proposal in proposals:
        aid = proposal["action_id"]
        events = [e for e in result["actions"] if e.get("action_id") == aid]
        status = events[-1]["status"]
        observations = [e for e in valid_evidence if e.get("kind") == "recovery_metrics"
                        and e.get("environment") == "lab" and e.get("data", {}).get("action_id") == aid
                        and e.get("data", {}).get("run_id") == run_id
                        and e.get("data", {}).get("environment_id") == proposal.get("environment_id")]
        latest = observations[-1] if observations else None
        # Even a previously verified observation cannot keep a rollback green.
        state = {"action_id": aid, "target": proposal.get("target"), "status": status,
                 "execution_mode": proposal.get("execution_mode", "simulation"),
                 "model_mode": proposal.get("model_mode", "unknown"),
                 "verification": "inconclusive", "observation": latest}
        if status == "executed" and latest and result["evidence_integrity"] == "valid":
            state["verification"] = latest["data"].get("verdict", "inconclusive")
        if status in {"execution_unknown", "rollback_unknown", "execution_dispatched", "rollback_dispatched"}:
            result["warnings"].append("operation_requires_reconciliation:" + aid)
        result["action_states"].append(state)
    result["warnings"].append("verification_is_a_point_in_time_observation_not_a_fresh_probe")
    result["export_sha256"] = digest(result)
    return result
