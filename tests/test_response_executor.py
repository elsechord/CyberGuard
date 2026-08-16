import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "response-executor"))
TEMP = tempfile.TemporaryDirectory()
os.environ["CYBERGUARD_DATA_DIR"] = TEMP.name
os.environ["CYBERGUARD_EXECUTOR_TOKEN"] = "test-executor-token"
os.environ["CYBERGUARD_APPROVAL_SECRET"] = "human-only-secret"
os.environ["CYBERGUARD_AUDIT_HMAC_KEY"] = "audit-key-separated-from-data-volume"
os.environ["CYBERGUARD_AUDIT_READER_TOKEN"] = "read-only-audit-verification-token"

from app.main import app, append_event  # noqa: E402


class ResponseExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-executor-token"}

    def propose(self, key: str = "incident-host-action-0001") -> dict:
        response = self.client.post(
            "/actions/propose",
            headers=self.headers,
            json={
                "incident_id": "CG-TEST-1",
                "action": "isolate_endpoint",
                "target": "FIN-LT-023",
                "reason": "Independent evidence confirms active compromise.",
                "idempotency_key": key,
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_concurrent_audit_appends_preserve_chain(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda index: append_event({"status": "test", "index": index}), range(24)))
        result = self.client.get("/audit/verify", headers=self.headers)
        self.assertTrue(result.json()["valid"])

    def test_execution_requires_approval(self) -> None:
        action = self.propose()
        response = self.client.post(f"/actions/{action['action_id']}/execute", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_approval_secret_and_rollback(self) -> None:
        action = self.propose("incident-host-action-0002")
        rejected = self.client.post(
            "/actions/approve",
            headers={**self.headers, "X-Approval-Secret": "wrong"},
            json={"action_id": action["action_id"], "approver": "analyst"},
        )
        self.assertEqual(rejected.status_code, 403)
        approved = self.client.post(
            "/actions/approve",
            headers={**self.headers, "X-Approval-Secret": "human-only-secret"},
            json={"action_id": action["action_id"], "approver": "analyst"},
        )
        self.assertEqual(approved.status_code, 200)
        executed = self.client.post(f"/actions/{action['action_id']}/execute", headers=self.headers)
        self.assertEqual(executed.json()["status"], "executed")
        audit = self.client.get("/audit/verify", headers=self.headers)
        self.assertTrue(audit.json()["valid"])
        rolled_back = self.client.post(f"/actions/{action['action_id']}/rollback", headers=self.headers)
        self.assertEqual(rolled_back.json()["status"], "rolled_back")

    def test_idempotent_proposal(self) -> None:
        first = self.propose("incident-host-action-0003")
        second = self.propose("incident-host-action-0003")
        self.assertEqual(first["action_id"], second["action_id"])

    def test_idempotency_key_cannot_be_rebound(self) -> None:
        self.propose("incident-host-action-conflict")
        response = self.client.post(
            "/actions/propose",
            headers=self.headers,
            json={
                "incident_id": "CG-TEST-1",
                "action": "isolate_endpoint",
                "target": "DIFFERENT-HOST",
                "reason": "Attempt to alter an already proposed action target.",
                "idempotency_key": "incident-host-action-conflict",
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_tampered_audit_is_detected(self) -> None:
        self.propose("incident-host-action-tamper")
        audit_path = Path(TEMP.name) / "actions.jsonl"
        content = audit_path.read_text(encoding="utf-8")
        audit_path.write_text(content.replace("FIN-LT-023", "ALTERED-HOST", 1), encoding="utf-8")
        result = self.client.get("/audit/verify", headers=self.headers)
        self.assertFalse(result.json()["valid"])

    def test_rehashed_data_volume_tampering_fails_hmac(self) -> None:
        self.propose("incident-host-action-rehash")
        audit_path = Path(TEMP.name) / "actions.jsonl"
        records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
        record = records[-1]
        record["target"] = "FORGED-HOST"
        record.pop("record_hmac_sha256")
        record.pop("record_sha256")
        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
        record["record_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        record["record_hmac_sha256"] = "0" * 64
        records[-1] = record
        audit_path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
        result = self.client.get("/audit/verify", headers=self.headers).json()
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "record_hmac_mismatch")

    def test_concurrent_execute_is_exactly_once_and_approval_cannot_replay(self) -> None:
        action = self.propose("incident-host-action-concurrent")
        approval = self.client.post(
            "/actions/approve",
            headers={**self.headers, "X-Approval-Secret": "human-only-secret"},
            json={"action_id": action["action_id"], "approver": "analyst"},
        )
        self.assertEqual(approval.status_code, 200)
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(
                lambda _: self.client.post(f"/actions/{action['action_id']}/execute", headers=self.headers),
                range(16),
            ))
        self.assertTrue(all(response.status_code == 200 for response in responses))
        history = self.client.get(f"/actions/{action['action_id']}", headers=self.headers).json()["events"]
        self.assertEqual(sum(event["status"] == "executed" for event in history), 1)
        replay = self.client.post(
            "/actions/approve",
            headers={**self.headers, "X-Approval-Secret": "human-only-secret"},
            json={"action_id": action["action_id"], "approver": "analyst"},
        )
        self.assertEqual(replay.status_code, 409)

    def test_checkpoint_and_read_only_incident_state_are_authenticated(self) -> None:
        checkpoint = self.client.get("/audit/checkpoint", headers=self.headers)
        self.assertEqual(checkpoint.status_code, 200)
        self.assertEqual(len(checkpoint.json()["checkpoint_hmac_sha256"]), 64)
        denied = self.client.get("/audit/incidents/CG-TEST-1/active", headers=self.headers)
        self.assertEqual(denied.status_code, 401)
        allowed = self.client.get(
            "/audit/incidents/CG-TEST-1/active",
            headers={"Authorization": "Bearer read-only-audit-verification-token"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertIn("active_executed_action", allowed.json())
        self.assertIn("active_actions", allowed.json())

    def test_audit_state_returns_exact_active_action_set(self) -> None:
        response = self.client.post(
            "/actions/propose", headers=self.headers,
            json={
                "incident_id": "CG-WORKLOAD-1", "action": "quarantine_workload",
                "target": "checkout-api", "reason": "Backdoored workload requires reversible quarantine.",
                "idempotency_key": "workload-quarantine-0001",
            },
        )
        self.assertEqual(response.status_code, 200)
        action = response.json()
        self.client.post(
            "/actions/approve",
            headers={**self.headers, "X-Approval-Secret": "human-only-secret"},
            json={"action_id": action["action_id"], "approver": "analyst"},
        ).raise_for_status()
        self.client.post(f"/actions/{action['action_id']}/execute", headers=self.headers).raise_for_status()
        state = self.client.get(
            "/audit/incidents/CG-WORKLOAD-1/active",
            headers={"Authorization": "Bearer read-only-audit-verification-token"},
        ).json()
        self.assertEqual(
            state["active_actions"],
            [{"action_id": action["action_id"], "action": "quarantine_workload", "target": "checkout-api", "status": "executed"}],
        )
        self.client.post(f"/actions/{action['action_id']}/rollback", headers=self.headers).raise_for_status()
        closed = self.client.get(
            "/audit/incidents/CG-WORKLOAD-1/active",
            headers={"Authorization": "Bearer read-only-audit-verification-token"},
        ).json()
        self.assertEqual(closed["active_actions"], [])

    def test_expired_approval_can_only_be_replaced_by_new_human_approval(self) -> None:
        action = self.propose("incident-host-action-expired")
        append_event({
            "action_id": action["action_id"],
            "incident_id": action["incident_id"],
            "proposal_record_sha256": action["record_sha256"],
            "approver": "analyst-old",
            "status": "approved",
            "approval_expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        })
        expired = self.client.post(f"/actions/{action['action_id']}/execute", headers=self.headers)
        self.assertEqual(expired.status_code, 409)
        renewed = self.client.post(
            "/actions/approve",
            headers={**self.headers, "X-Approval-Secret": "human-only-secret"},
            json={"action_id": action["action_id"], "approver": "analyst-new"},
        )
        self.assertEqual(renewed.status_code, 200)
        self.assertEqual(renewed.json()["supersedes_approval_record_sha256"],
                         self.client.get(f"/actions/{action['action_id']}", headers=self.headers).json()["events"][-2]["record_sha256"])


if __name__ == "__main__":
    unittest.main()
