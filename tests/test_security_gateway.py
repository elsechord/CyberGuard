import os
import sys
import tempfile
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "security-tool-gateway"))
os.environ["CYBERGUARD_API_TOKEN"] = "test-read-token"
os.environ["CYBERGUARD_SCENARIO_DIR"] = str(ROOT / "scenarios")
TEMP = tempfile.TemporaryDirectory()
os.environ["CYBERGUARD_DATA_DIR"] = TEMP.name
os.environ["CYBERGUARD_ACTION_AUDIT_FILE"] = str(Path(TEMP.name) / "actions.jsonl")
os.environ["CYBERGUARD_LIVE_CONNECTORS_FILE"] = str(Path(TEMP.name) / "connectors.json")
os.environ["CYBERGUARD_KNOWLEDGE_DIR"] = str(ROOT / "knowledge")

from app.main import app  # noqa: E402


class SecurityGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-read-token"}

    def test_requires_authentication(self) -> None:
        self.assertEqual(self.client.get("/tools").status_code, 401)

    def test_collects_hash_bound_evidence(self) -> None:
        response = self.client.post(
            "/tools/endpoint/timeline",
            headers=self.headers,
            json={"incident_id": "CG-TEST-1", "scenario_id": "credential_compromise"},
        )
        self.assertEqual(response.status_code, 200)
        evidence = response.json()["evidence"]
        self.assertEqual(evidence["incident_id"], "CG-TEST-1")
        self.assertEqual(len(evidence["sha256"]), 64)
        self.assertIn("H3-persistence", evidence["supports"])
        self.assertEqual(evidence["standard"]["schema"], "cyberguard-security-observation")
        self.assertEqual(evidence["standard"]["raw_sha256"], evidence["sha256"])
        self.assertEqual(evidence["standard"]["alignment"]["cti_profile"], "STIX-2.1")
        self.assertEqual(evidence["quality"]["gate"], "pass")
        self.assertIn("T1053.005", evidence["attack_techniques"])

    def test_evidence_validation_rejects_invented_ids(self) -> None:
        collected = self.client.post(
            "/tools/alert/snapshot", headers=self.headers,
            json={"incident_id": "CG-EVIDENCE-GATE", "scenario_id": "credential_compromise"},
        ).json()["evidence"]
        response = self.client.post(
            "/evidence/CG-EVIDENCE-GATE/validate", headers=self.headers,
            json={"evidence_ids": [collected["evidence_id"], "EV-NOT-REAL"]},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertFalse(result["valid"])
        self.assertEqual(result["resolved_count"], 1)
        self.assertEqual(result["unknown_evidence_ids"], ["EV-NOT-REAL"])

    def test_knowledge_results_are_versioned_and_not_evidence(self) -> None:
        response = self.client.post(
            "/knowledge/search", headers=self.headers,
            json={"query": "MFA fatigue T1078", "limit": 3},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"]
        self.assertTrue(result)
        self.assertEqual(result[0]["document_id"], "KB-ATTACK-T1078")
        self.assertEqual(len(result[0]["content_hash"]), 64)
        self.assertIn("不是当前事件的事实证据", result[0]["disclaimer"])

    def test_workflow_isolated_sessions_and_approval_notification(self) -> None:
        incident = "CG-WORKFLOW-1"
        for session in ("session-a", "session-b"):
            response = self.client.post(
                f"/incidents/{incident}/workflow", headers=self.headers,
                json={"session_id": session, "state": "received", "actor": "manager"},
            )
            self.assertEqual(response.status_code, 200)
        for state in ("investigating", "evidence_validation", "awaiting_approval"):
            response = self.client.post(
                f"/incidents/{incident}/workflow", headers=self.headers,
                json={"session_id": "session-a", "state": state,
                      "actor": "response-planner", "message": "中文状态通知"},
            )
            self.assertEqual(response.status_code, 200)
        result = self.client.get(
            f"/incidents/{incident}/workflow", headers=self.headers,
        ).json()
        self.assertEqual(len(result["sessions"]), 2)
        self.assertEqual(result["awaiting_approval"][0]["session_id"], "session-a")
        session_b = self.client.get(
            f"/incidents/{incident}/workflow?session_id=session-b", headers=self.headers,
        ).json()
        self.assertEqual(session_b["state"], "received")

    def test_workflow_rejects_skipped_approval_transition(self) -> None:
        incident = "CG-WORKFLOW-INVALID"
        self.client.post(
            f"/incidents/{incident}/workflow", headers=self.headers,
            json={"session_id": "session-x", "state": "received", "actor": "manager"},
        )
        response = self.client.post(
            f"/incidents/{incident}/workflow", headers=self.headers,
            json={"session_id": "session-x", "state": "executing", "actor": "worker"},
        )
        self.assertEqual(response.status_code, 409)

    def test_recovery_fails_closed_when_authenticated_audit_is_unavailable(self) -> None:
        previous_url = os.environ.get("CYBERGUARD_AUDIT_VERIFY_URL")
        os.environ["CYBERGUARD_AUDIT_VERIFY_URL"] = "http://response-executor:8080"
        os.environ["CYBERGUARD_AUDIT_READER_TOKEN"] = "read-only-test-token"
        try:
            with patch("app.store.urlopen", side_effect=URLError("unavailable")):
                response = self.client.post(
                    "/tools/recovery/metrics",
                    headers=self.headers,
                    json={"incident_id": "CG-AUDIT-DOWN", "scenario_id": "credential_compromise"},
                )
            self.assertEqual(response.status_code, 200)
            data = response.json()["evidence"]["data"]
            self.assertEqual(data["verdict"], "inconclusive")
            self.assertEqual(data["reason"], "authenticated_audit_unavailable")
        finally:
            if previous_url is None:
                os.environ.pop("CYBERGUARD_AUDIT_VERIFY_URL", None)
            else:
                os.environ["CYBERGUARD_AUDIT_VERIFY_URL"] = previous_url

    def test_authenticated_recovery_requires_exact_action_and_target_set(self) -> None:
        class AuditResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return json.dumps({
                    "active_actions": [
                        {"action_id": "ACT-1", "action": "disable_account", "target": "finance-ops"},
                        {"action_id": "ACT-2", "action": "isolate_endpoint", "target": "FIN-LT-023"},
                        {"action_id": "ACT-3", "action": "block_ioc", "target": "198.51.100.27"},
                    ]
                }).encode()

        previous_url = os.environ.get("CYBERGUARD_AUDIT_VERIFY_URL")
        os.environ["CYBERGUARD_AUDIT_VERIFY_URL"] = "http://response-executor:8080"
        os.environ["CYBERGUARD_AUDIT_READER_TOKEN"] = "read-only-test-token"
        try:
            with patch("app.store.urlopen", return_value=AuditResponse()):
                response = self.client.post(
                    "/tools/recovery/metrics", headers=self.headers,
                    json={"incident_id": "CG-AUTH-EXACT", "scenario_id": "credential_compromise"},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["evidence"]["data"]["verdict"], "verified")
        finally:
            if previous_url is None:
                os.environ.pop("CYBERGUARD_AUDIT_VERIFY_URL", None)
            else:
                os.environ["CYBERGUARD_AUDIT_VERIFY_URL"] = previous_url

    def test_live_connector_keeps_destination_and_secret_server_side(self) -> None:
        captured: dict = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                length = int(self.headers.get("Content-Length", "0"))
                captured["body"] = json.loads(self.rfile.read(length))
                payload = json.dumps({
                    "source": "forged-upstream-source",
                    "handling": "public",
                    "summary": "Live SIEM result",
                    "observed_at": "2026-08-13T08:00:00Z",
                    "supports": ["H1-live-alert"],
                    "attack_techniques": ["T1078"],
                    "data": {"account": "finance-ops", "alerts": ["A-1"]},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = {
                "connectors": {
                    "alert.snapshot": {
                        "base_url_env": "TEST_SIEM_URL",
                        "token_env": "TEST_SIEM_TOKEN",
                        "path": "/fixed/search",
                        "method": "POST",
                        "source": "test-siem"
                    }
                }
            }
            Path(os.environ["CYBERGUARD_LIVE_CONNECTORS_FILE"]).write_text(
                json.dumps(config), encoding="utf-8"
            )
            os.environ["TEST_SIEM_URL"] = f"http://127.0.0.1:{server.server_port}"
            os.environ["TEST_SIEM_TOKEN"] = "upstream-secret"
            os.environ["CYBERGUARD_ALLOW_INSECURE_HTTP"] = "1"
            response = self.client.post(
                "/tools/alert/snapshot",
                headers=self.headers,
                json={
                    "incident_id": "CG-LIVE-1",
                    "scenario_id": "live",
                    "arguments": {"query": "severity:P1", "url": "http://attacker.invalid"}
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(captured["path"], "/fixed/search")
            self.assertEqual(captured["authorization"], "Bearer upstream-secret")
            self.assertEqual(captured["body"]["query"], "severity:P1")
            self.assertEqual(response.json()["evidence"]["source"], "test-siem")
            self.assertEqual(response.json()["evidence"]["handling"], "restricted")
            self.assertGreaterEqual(response.json()["evidence"]["quality"]["score"], 0.7)
        finally:
            server.shutdown()
            server.server_close()

    def test_live_connector_rejects_low_quality_evidence(self) -> None:
        poor = {
            "source": "live:test", "kind": "alert", "summary": "Unstructured result",
            "confidence": 0.7, "data": {"alerts": ["A-1"]},
        }
        with patch("app.store.live_connectors.invoke", return_value=poor):
            response = self.client.post(
                "/tools/alert/snapshot", headers=self.headers,
                json={"incident_id": "CG-LOW-QUALITY", "scenario_id": "live"},
            )
        self.assertEqual(response.status_code, 502)
        self.assertIn("failed quality gate", response.json()["detail"])
        evidence = self.client.get("/evidence/CG-LOW-QUALITY", headers=self.headers).json()["evidence"]
        self.assertEqual(evidence, [])

    def test_incident_index_detail_graph_and_console(self) -> None:
        for tool in ("alert/snapshot", "endpoint/timeline"):
            response = self.client.post(
                f"/tools/{tool}",
                headers=self.headers,
                json={"incident_id": "CG-DASHBOARD", "scenario_id": "credential_compromise"},
            )
            self.assertEqual(response.status_code, 200)
        index = self.client.get("/incidents", headers=self.headers)
        self.assertTrue(any(item["incident_id"] == "CG-DASHBOARD" for item in index.json()["incidents"]))
        detail = self.client.get("/incidents/CG-DASHBOARD", headers=self.headers)
        self.assertEqual(detail.json()["summary"]["evidence_count"], 2)
        graph = self.client.get("/incidents/CG-DASHBOARD/graph", headers=self.headers)
        node_types = {item["type"] for item in graph.json()["nodes"]}
        self.assertTrue({"incident", "source", "evidence", "hypothesis", "entity", "attack_technique"}.issubset(node_types))
        console = self.client.get("/console")
        self.assertEqual(console.status_code, 200)
        self.assertIn("default-src 'self'", console.headers["content-security-policy"])
        self.assertNotIn("unsafe-inline", console.headers["content-security-policy"])

    def test_cross_source_entity_correlation_and_quality_gate(self) -> None:
        for tool in ("network/search", "endpoint/timeline", "asset/context"):
            response = self.client.post(
                f"/tools/{tool}", headers=self.headers,
                json={"incident_id": "CG-CORRELATION", "scenario_id": "credential_compromise"},
            )
            self.assertEqual(response.status_code, 200)
        graph = self.client.get("/incidents/CG-CORRELATION/graph", headers=self.headers).json()
        host = next(node for node in graph["nodes"] if node.get("label") == "FIN-LT-023")
        mentions = [edge for edge in graph["edges"] if edge["target"] == host["id"] and edge["type"] == "mentions"]
        self.assertEqual(len(mentions), 3)
        quality = self.client.get("/incidents/CG-CORRELATION/quality", headers=self.headers)
        self.assertEqual(quality.status_code, 200)
        self.assertEqual(quality.json()["gate"], "pass")
        self.assertEqual(quality.json()["source_count"], 3)
        summary = self.client.get("/incidents/CG-CORRELATION", headers=self.headers).json()["summary"]
        self.assertGreaterEqual(summary["cross_source_entity_count"], 1)

    def test_unknown_scenario_is_not_leaked(self) -> None:
        response = self.client.post(
            "/tools/alert/snapshot",
            headers=self.headers,
            json={"incident_id": "CG-TEST-2", "scenario_id": "../secret"},
        )
        self.assertEqual(response.status_code, 404)

    def test_recovery_fails_closed_without_executed_action(self) -> None:
        response = self.client.post(
            "/tools/recovery/metrics",
            headers=self.headers,
            json={"incident_id": "CG-NO-ACTION", "scenario_id": "credential_compromise"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["evidence"]["data"]
        self.assertFalse(data["endpoint_isolated"])
        self.assertEqual(data["verdict"], "inconclusive")

    def test_recovery_uses_active_execution_state(self) -> None:
        audit = Path(TEMP.name) / "actions.jsonl"
        audit.write_text(
            '{"action_id":"ACT-test-1","incident_id":"CG-ACTION","action":"disable_account","target":"finance-ops","status":"executed"}\n'
            '{"action_id":"ACT-test-2","incident_id":"CG-ACTION","action":"isolate_endpoint","target":"FIN-LT-023","status":"executed"}\n'
            '{"action_id":"ACT-test-3","incident_id":"CG-ACTION","action":"block_ioc","target":"198.51.100.27","status":"executed"}\n',
            encoding="utf-8",
        )
        response = self.client.post(
            "/tools/recovery/metrics",
            headers=self.headers,
            json={"incident_id": "CG-ACTION", "scenario_id": "credential_compromise"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["evidence"]["data"]["endpoint_isolated"])
        self.assertTrue(response.json()["evidence"]["data"]["required_actions_met"])

    def test_recovery_rejects_unrelated_or_partial_actions(self) -> None:
        audit = Path(TEMP.name) / "actions.jsonl"
        audit.write_text(
            '{"action_id":"ACT-wrong","incident_id":"CG-WRONG-ACTION","action":"block_ioc","target":"203.0.113.99","status":"executed"}\n',
            encoding="utf-8",
        )
        response = self.client.post(
            "/tools/recovery/metrics", headers=self.headers,
            json={"incident_id": "CG-WRONG-ACTION", "scenario_id": "credential_compromise"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["evidence"]["data"]
        self.assertEqual(data["verdict"], "inconclusive")
        self.assertEqual(data["reason"], "required_response_not_satisfied")
        self.assertEqual(len(data["missing_required_actions"]), 3)
        summary = self.client.get(
            "/incidents/CG-WRONG-ACTION", headers=self.headers
        ).json()["summary"]
        self.assertEqual(summary["status"], "responding")

    def test_boundary_policy_is_hash_bound_and_correlatable(self) -> None:
        self.assertIn("boundary.policy", self.client.get("/tools", headers=self.headers).json()["tools"])
        response = self.client.post(
            "/tools/boundary/policy", headers=self.headers,
            json={"incident_id": "CG-BOUNDARY", "scenario_id": "credential_compromise"},
        )
        self.assertEqual(response.status_code, 200)
        evidence = response.json()["evidence"]
        self.assertEqual(evidence["standard"]["class_name"], "network_security_policy")
        self.assertIn("T1041", evidence["attack_techniques"])
        self.assertTrue(any(item["type"] == "security_appliance" for item in evidence["entities"]))
        self.assertTrue(any(item["value"] == "198.51.100.27" for item in evidence["observables"]))


if __name__ == "__main__":
    unittest.main()
