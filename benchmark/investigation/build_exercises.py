"""Maintainer-only exercise builder. Never expose this or evaluator-only to agents.

These are authored synthetic observations, not recorded attacks. They test
contract/rule behavior; they cannot measure field accuracy or generalization.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from cyberguard_investigation.evidence import make_artifact, make_bundle, canonical_bytes, validate_bundle

NOW = "2026-09-17T00:00:00+00:00"
OUTPUT = Path(__file__).resolve().parent


def digest(value, field):
    return hashlib.sha256(canonical_bytes({k: v for k, v in value.items() if k != field})).hexdigest()


def build():
    (OUTPUT / "cases").mkdir(exist_ok=True)
    (OUTPUT / "evaluator-only").mkdir(exist_ok=True)
    for index in (1, 2, 3):
        case_id = f"case-{index:03d}"
        artifacts = []

        def add(kind, source, data, status="collected"):
            artifact = make_artifact(kind, source, data, status=status, observed_at=NOW, collected_at=NOW)
            artifact["evidence_id"] = "EV-" + hashlib.sha256(f"{case_id}/{len(artifacts)}".encode()).hexdigest()[:32]
            artifact["sha256"] = digest(artifact, "sha256")
            artifacts.append(artifact)
            return artifact["evidence_id"]

        path = "/var/tmp/task-worker" if index == 1 else "/opt/tasks/batch-worker"
        process = add("processes", "exercise:/proc sampled observations", {"processes": [
            {"pid": 423, "ppid": 1, "uid": 1001, "comm": "task-worker", "exe": path,
             "starttime_ticks": 412300, "cpu_percent": 86.2, "cpu_observation_status": "measured"},
            {"pid": 512, "ppid": 1, "uid": 1001, "comm": "web-worker", "exe": "/opt/web/server",
             "starttime_ticks": 312300, "cpu_percent": 3.1, "cpu_observation_status": "measured"}],
            "sample_seconds": 2, "coverage": {"sampled_processes": 2, "complete_host_coverage": False}})
        add("network", "exercise:/proc/net/tcp", {"connections": [{"protocol": "tcp", "local_address": "192.0.2.10", "local_port": 43892,
            "remote_address": "198.51.100.20", "remote_port": 443, "state": "01", "inode": "119", "owner_pids": [423]}],
            "coverage": {"scope": "one supplied network observation", "payload_collected": False}})
        if index == 1:
            persistence = add("persistence", "exercise:/etc/systemd/system/task-worker.service", {"entries": [
                {"mechanism": "systemd", "path": "/etc/systemd/system/task-worker.service", "command": path,
                 "enabled": None, "section": "Service", "unit": "task-worker.service"}],
                "coverage": {"scope": "one supplied configuration", "scheduler_state_collected": False}})
            add("auth_logs", "exercise:provided auth excerpt", {"events": [{"line": 1, "text": "Sep 17 00:00:00 host sshd: Failed publickey for user from 203.0.113.5"}],
                "coverage": {"complete_window": False}})
            expected = [{"finding_type": "suspicious_persistence", "status": "supported", "required_evidence_ids": [process, persistence]}]
        elif index == 2:
            add("persistence", "exercise:/etc/systemd/system/batch-worker.service", {"entries": [
                {"mechanism": "systemd", "path": "/etc/systemd/system/batch-worker.service", "command": path,
                 "enabled": None}], "coverage": {"scope": "one supplied configuration"}})
            inventory = add("workload_inventory", "exercise:asset-owner workload record", {"entries": [
                {"exe": path, "owner": "operations", "purpose": "scheduled rendering workload", "authorization": "approved"}]})
            add("auth_logs", "exercise:provided auth excerpt", {"events": [], "coverage": {"complete_window": False}})
            expected = [{"finding_type": "authorized_workload", "status": "supported", "required_evidence_ids": [process, inventory]}]
        else:
            add("persistence", "exercise:scheduler directory", {"reason": "collector lacked read permission", "entries": []}, "unavailable")
            add("auth_logs", "exercise:authentication log", {"reason": "requested incident window was not retained", "events": []}, "unavailable")
            expected = [{"finding_type": "unclassified_workload", "status": "inconclusive", "required_evidence_ids": [process]}]
        bundle = make_bundle(artifacts, provenance={"kind": "exercise", "description": "Authored synthetic Linux observations; no real victim, attack or mining."}, bundle_id="EXERCISE-" + case_id)
        bundle["created_at"] = NOW
        bundle["bundle_sha256"] = digest(bundle, "bundle_sha256")
        validate_bundle(bundle)
        expected += [{"finding_type": "entrypoint", "status": "inconclusive"}, {"finding_type": "attribution", "status": "inconclusive"}]
        rubric = {"schema": "cyberguard-investigation-exercise-rubric/v1", "kind": "exercise_ground_truth",
                  "bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["bundle_sha256"],
                  "expected_findings": expected, "no_state_changing_suggestions": True,
                  "limitations": "Authored scenario expectations, not independently established incident ground truth; do not expose to evaluated agents."}
        for path, data in ((OUTPUT / "cases" / (case_id + ".json"), bundle), (OUTPUT / "evaluator-only" / (case_id + ".json"), rubric)):
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
