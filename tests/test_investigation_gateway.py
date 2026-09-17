"""Role separation, immutable run binding, citation checks and persisted quotas."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services/security-tool-gateway"))
TEMP = tempfile.TemporaryDirectory()
os.environ.update(CYBERGUARD_DATA_DIR=TEMP.name, CYBERGUARD_API_TOKEN="r" * 40,
                  CYBERGUARD_INVESTIGATION_INGEST_TOKEN="i" * 40, CYBERGUARD_REPORT_TOKEN="p" * 40)
from app.main import app
from cyberguard_investigation.evidence import make_artifact, make_bundle


class InvestigationGatewayTests(unittest.TestCase):
    def setUp(self):
        (Path(TEMP.name) / "investigations.sqlite").unlink(missing_ok=True)
        self.client = TestClient(app)
        self.reader = {"Authorization": "Bearer " + "r" * 40}
        self.ingest = {"Authorization": "Bearer " + "i" * 40}
        self.reporter = {"Authorization": "Bearer " + "p" * 40}
        self.bundle = make_bundle([make_artifact("process_snapshot", "test-collector", {"processes": []})],
                                  provenance={"kind": "exercise"})

    def prepare(self, calls=16, mode="fixed_workflow"):
        imported = self.client.post("/investigations/bundles", json=self.bundle, headers=self.ingest)
        self.assertEqual(imported.status_code, 200, imported.text)
        response = self.client.post("/investigations/runs", headers=self.ingest, json={
            "run_id": "RUN-TEST-001", "bundle_id": self.bundle["bundle_id"], "mode": mode,
            "budget": {"max_input_tokens": 20000, "max_output_tokens": 8000, "max_tool_calls": calls}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def report(self, mode="fixed_workflow"):
        return {"schema": "cyberguard-investigation-report/v1", "bundle_id": self.bundle["bundle_id"],
            "bundle_sha256": self.bundle["bundle_sha256"], "mode": mode,
            "findings": [{"claim": "Insufficient evidence to establish an intrusion.", "status": "inconclusive",
                          "supporting_evidence_ids": [], "contradicting_evidence_ids": [], "limitations": ["No incident logs."]}],
            "unknowns": ["Initial access and actor unknown."], "next_collection": ["Collect scoped incident logs."], "proposed_actions": []}

    def test_reader_cannot_import_or_submit_and_reporter_cannot_read_or_create(self):
        self.assertEqual(self.client.post("/investigations/bundles", headers=self.reader, json=self.bundle).status_code, 401)
        self.prepare()
        self.assertEqual(self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reader, json=self.report()).status_code, 401)
        self.assertEqual(self.client.get("/investigations/runs/RUN-TEST-001/evidence", headers=self.reporter).status_code, 401)
        self.assertEqual(self.client.post("/investigations/runs", headers=self.reporter, json={}).status_code, 401)

    def test_same_run_read_submit_export_does_not_attest_model_execution(self):
        run = self.prepare()
        observation = self.client.get("/investigations/runs/RUN-TEST-001/evidence", headers=self.reader)
        self.assertEqual(observation.status_code, 200)
        self.assertEqual(observation.headers["cache-control"], "no-store")
        self.assertEqual(observation.json()["bundle"], self.bundle)
        submitted = self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=self.report())
        self.assertEqual(submitted.status_code, 200, submitted.text)
        result = submitted.json()
        self.assertEqual(result["validation"]["model_execution"], "not_attested")
        self.assertFalse(result["validation"]["actions_executed"])
        repeated = self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=self.report())
        self.assertEqual(result, repeated.json())
        exported = self.client.get("/investigations/runs/RUN-TEST-001/reports", headers=self.reader).json()
        self.assertEqual(exported["tool_calls_used"], 2)
        self.assertEqual(exported["run"]["run_sha256"], run["run_sha256"])
        self.assertEqual(exported["runtime_status"], "not_attested")

    def test_model_client_accepts_actual_gateway_contract(self):
        from cyberguard_investigation.model_runner import EvidenceTools, ModelRunError
        self.prepare(mode="single_agent")
        tools = EvidenceTools(self.bundle, "RUN-TEST-001", gateway_url="http://127.0.0.1:18100",
                              reader_token="r" * 40, report_token="p" * 40)

        def transport(url, token, payload=None, **kwargs):
            headers = {"Authorization": "Bearer " + token}
            path = urlsplit(url).path
            response = (self.client.get(path, headers=headers) if payload is None else
                        self.client.post(path, headers=headers, json=payload))
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        with patch("cyberguard_investigation.model_runner.http_json", side_effect=transport):
            tools.prepare()
            tools.call("read_evidence_bundle", {})
            report = self.report("single_agent")
            report["findings"][0]["finding_type"] = "entrypoint"
            acknowledgement = tools.call("submit_investigation_report", {"report": report})
            self.assertEqual(acknowledgement["report"], report)
            self.assertEqual(tools.gateway_sequence, 2)
            reused = EvidenceTools(self.bundle, "RUN-TEST-001", gateway_url="http://127.0.0.1:18100",
                                   reader_token="r" * 40, report_token="p" * 40)
            with self.assertRaisesRegex(ModelRunError, "not_fresh"):
                reused.prepare()

    def test_schema_validation_never_promotes_fake_or_foreign_citations(self):
        self.prepare()
        report = self.report()
        report["findings"][0].update(status="supported", supporting_evidence_ids=["EV-NONEXISTENT"])
        self.assertEqual(self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=report).status_code, 422)
        report = self.report()
        report["bundle_sha256"] = "0" * 64
        self.assertEqual(self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=report).status_code, 422)
        report = self.report()
        report["run_id"] = "different-run"
        self.assertEqual(self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=report).status_code, 422)

    def test_run_mode_and_budget_cannot_be_rebound_and_tools_equal(self):
        first = self.prepare()
        altered = self.client.post("/investigations/runs", headers=self.ingest, json={
            "run_id": first["run_id"], "bundle_id": self.bundle["bundle_id"], "mode": "multi_agent"})
        self.assertEqual(altered.status_code, 409)
        second = self.client.post("/investigations/runs", headers=self.ingest, json={
            "run_id": "RUN-MULTI-001", "bundle_id": self.bundle["bundle_id"], "mode": "multi_agent"}).json()
        self.assertEqual(first["tool_scope"], second["tool_scope"])
        wrong_mode = self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=self.report("multi_agent"))
        self.assertEqual(wrong_mode.status_code, 422)

    def test_budget_exhaustion_survives_new_client_and_duplicate_submission(self):
        self.prepare(calls=2)
        self.client.get("/investigations/runs/RUN-TEST-001/evidence", headers=self.reader)
        report = self.report()
        first = self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=report)
        self.assertEqual(first.status_code, 200, first.text)
        self.client = TestClient(app)
        self.assertEqual(self.client.get("/investigations/runs/RUN-TEST-001/evidence", headers=self.reader).status_code, 429)
        duplicate = self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=report)
        self.assertEqual(duplicate.json(), first.json())

    def test_modified_bundle_and_stored_report_fail_closed(self):
        self.prepare()
        submitted = self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=self.report())
        self.assertEqual(submitted.status_code, 200, submitted.text)
        with sqlite3.connect(Path(TEMP.name) / "investigations.sqlite") as db:
            stored = submitted.json()
            stored["report"]["unknowns"] = []
            db.execute("UPDATE reports SET payload=?", (json.dumps(stored),))
        db.close()
        self.assertEqual(self.client.get("/investigations/runs/RUN-TEST-001/reports", headers=self.reader).status_code, 409)
        self.assertEqual(self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=self.report()).status_code, 409)
        with sqlite3.connect(Path(TEMP.name) / "investigations.sqlite") as db:
            self.bundle["artifacts"][0]["data"] = {"forged": True}
            db.execute("UPDATE bundles SET payload=?", (json.dumps(self.bundle),))
        db.close()
        self.assertEqual(self.client.get("/investigations/runs/RUN-TEST-001/evidence", headers=self.reader).status_code, 409)

    def test_reused_role_secret_fails_closed(self):
        old = os.environ["CYBERGUARD_REPORT_TOKEN"]
        try:
            os.environ["CYBERGUARD_REPORT_TOKEN"] = os.environ["CYBERGUARD_API_TOKEN"]
            self.prepare()
            self.assertEqual(self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reader, json=self.report()).status_code, 503)
        finally:
            os.environ["CYBERGUARD_REPORT_TOKEN"] = old

    def test_malformed_report_run_id_is_a_client_error(self):
        self.prepare()
        for value in ({}, [], 123):
            with self.subTest(value=value):
                report = self.report()
                report["run_id"] = value
                self.assertEqual(self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=report).status_code, 422)

    def test_valid_receipt_from_another_run_is_rejected_on_read_and_write(self):
        self.prepare()
        self.client.get("/investigations/runs/RUN-TEST-001/evidence", headers=self.reader)
        self.client.post("/investigations/runs", headers=self.ingest, json={
            "run_id": "RUN-OTHER-001", "bundle_id": self.bundle["bundle_id"], "mode": "fixed_workflow"})
        other = self.client.get("/investigations/runs/RUN-OTHER-001/evidence", headers=self.reader).json()["tool_receipt"]
        with sqlite3.connect(Path(TEMP.name) / "investigations.sqlite") as db:
            db.execute("UPDATE investigation_events SET payload=? WHERE run_id=?", (json.dumps(other), "RUN-TEST-001"))
        db.close()
        self.assertEqual(self.client.get("/investigations/runs/RUN-TEST-001/reports", headers=self.reader).status_code, 409)
        self.assertEqual(self.client.get("/investigations/runs/RUN-TEST-001/evidence", headers=self.reader).status_code, 409)
        self.assertEqual(self.client.post("/investigations/runs/RUN-TEST-001/reports", headers=self.reporter, json=self.report()).status_code, 409)


if __name__ == "__main__":
    unittest.main()
