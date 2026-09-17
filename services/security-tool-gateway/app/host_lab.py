"""Read-only Linux laboratory observations, separate from response receipts."""
import os
import time
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import uuid4

from .lab_verification import ProbeError, origin, read


def snapshot(environment_id=None):
    nonce = uuid4().hex
    _, payload = read(origin("CYBERGUARD_HOST_LAB_URL") + "/snapshot?nonce=" + nonce,
                      os.getenv("CYBERGUARD_HOST_READER_TOKEN", ""))
    if (payload.get("nonce") != nonce or payload.get("environment") != "lab"
            or not payload.get("environment_id")
            or environment_id is not None and payload["environment_id"] != environment_id
            or not isinstance(payload.get("processes"), list)
            or not isinstance(payload.get("persistence", {}).get("present"), bool)):
        raise ProbeError("host snapshot identity or freshness mismatch")
    return payload


def record(kind, data, summary):
    return {"source": "linux-host-lab-collector", "kind": kind, "data": data,
            "observed_at": datetime.now(UTC).isoformat(), "confidence": 1.0,
            "summary": summary, "handling": "internal"}


def collect():
    return record("endpoint_timeline", snapshot(),
        "Observed /proc identities, supervisor file and local events; benign laboratory, not incident attribution.")


def active_action(incident_id, run_id, action_id):
    _, audit = read(origin("CYBERGUARD_AUDIT_VERIFY_URL") + "/audit/incidents/" +
                    quote(incident_id, safe="") + "/active", os.getenv("CYBERGUARD_AUDIT_READER_TOKEN", ""))
    matches = [a for a in audit.get("active_actions", []) if isinstance(a, dict)
               and a.get("action_id") == action_id and a.get("run_id") == run_id
               and a.get("action") in {"terminate_process", "disable_persistence"}
               and a.get("execution_mode") == "host_lab" and a.get("environment_id")]
    if len(matches) != 1:
        raise ProbeError("no matching executed host action")
    return matches[0], audit


def verify(incident_id, arguments):
    run_id, action_id = arguments.get("run_id"), arguments.get("action_id")
    if not all(isinstance(v, str) and 3 <= len(v) <= 128 for v in (run_id, action_id)):
        raise ProbeError("run_id and action_id required")
    data = {"run_id": run_id, "action_id": action_id, "environment": "lab", "execution": "real",
            "verdict": "inconclusive", "telemetry_health": "unknown", "checks": [],
            "verification_scope": "bounded_lab_process_and_persistence_observation",
            "limitations": ["Not a permanent recovery guarantee or a real intrusion investigation.",
                            "No host isolation, entry point repair or adversary attribution is verified."]}
    try:
        action, _ = active_action(incident_id, run_id, action_id)
        data["environment_id"] = action["environment_id"]
        started = time.monotonic()
        for index in range(3):
            if index:
                time.sleep(1.1)
            observed = snapshot(action["environment_id"])
            data["checks"].append(observed)
            if observed.get("last_mutation") != {"action_id": action_id, "run_id": run_id, "result": "applied"}:
                raise ProbeError("another action changed the observation scope")
        data["observation_seconds"] = round(time.monotonic() - started, 3)
        current, audit = active_action(incident_id, run_id, action_id)
        if current != action:
            raise ProbeError("action changed during observation")
        checks = data["checks"]
        controls = [[p for p in s["processes"] if p.get("role") == "control"] for s in checks]
        if any(len(p) != 1 or not isinstance(p[0].get("heartbeat"), dict) for p in controls):
            raise ProbeError("control workload unavailable")
        controls = [p[0] for p in controls]
        if (len({p["target_ref"] for p in controls}) != 1
                or not all(b["heartbeat"]["sequence"] > a["heartbeat"]["sequence"]
                           for a, b in zip(controls, controls[1:]))):
            raise ProbeError("control identity changed or heartbeat stopped")
        persistence_absent = all(s["persistence"]["present"] is False for s in checks)
        target_absent = all(not any(p.get("role") == "compute" for p in s["processes"]) for s in checks)
        data.update(telemetry_health="healthy", verdict="verified" if persistence_absent and target_absent else "failed",
                    reason="bounded_recovery_observed" if persistence_absent and target_absent else "residual_process_or_persistence",
                    layers={"target_absent_through_window": target_absent,
                            "persistence_removed": persistence_absent, "control_workload_progressing": True},
                    audit_head=audit.get("audit_head"))
    except (ProbeError, OSError, ValueError, TypeError, KeyError):
        data["reason"] = "telemetry_unavailable_or_action_binding_invalid"
    return record("recovery_metrics", data,
                  "Independent bounded recovery observation; an applied action does not establish recovery.")
