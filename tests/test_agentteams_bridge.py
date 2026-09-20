"""Transport fixtures validate orchestration; they are not live runtime evidence."""
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("agentteams_bridge", ROOT / "services/operations-console/app/agentteams_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.roles = {r: {"room_id": "!" + r + ":test", "sender_id": "@" + r + ":test"} for r in bridge.ROLES}
        self.env = patch.dict(os.environ, {
            "CYBERGUARD_AGENTTEAMS_MATRIX_URL": "http://127.0.0.1:18080",
            "CYBERGUARD_AGENTTEAMS_MATRIX_TOKEN": "test-private-token",
            "CYBERGUARD_AGENTTEAMS_ROLES_JSON": json.dumps(self.roles)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.job = {"id": "job-1", "title": "Review", "objective": "Explain evidence", "domain": "endpoint",
                    "materials": [{"material_id": "m1", "content": "observed login", "name": "log"}], "bridge_state": {}}

    def report(self, role):
        return {"job_id": "job-1", "role": role, "summary": "Observed a login",
                "findings": [{"claim": "A login is recorded", "status": "supported", "limitations": "Attribution unknown",
                              "citations": [{"material_id": "m1", "quote": "observed login"}]}],
                "unknowns": ["Attribution"], "next_steps": ["Collect identity logs"]}

    def test_prepare_is_persisted_before_send_and_crash_retry_same_transaction(self):
        with patch.object(bridge, "_http", return_value={"next_batch": "cursor-before-send"}) as http:
            result = bridge.advance(self.job)
            self.assertEqual(http.call_args.args[1], "GET")
            self.assertNotIn("request_event_id", result["bridge_state"])
        self.job["bridge_state"] = result["bridge_state"]
        with patch.object(bridge, "_http", return_value={"event_id": "$sent"}) as http:
            bridge.advance(self.job)
            first = http.call_args.args
            bridge.advance(self.job)  # crash before prior result persisted
            self.assertEqual(first, http.call_args.args)
            self.assertEqual(first[1], "PUT")

    def test_three_workers_and_final_evidence_bound_report(self):
        for role in bridge.ROLES:
            with patch.object(bridge, "_http", return_value={"next_batch": "cursor"}):
                self.job["bridge_state"] = bridge.advance(self.job)["bridge_state"]
            with patch.object(bridge, "_http", return_value={"event_id": "$request-" + role}):
                self.job["bridge_state"] = bridge.advance(self.job)["bridge_state"]
            event = {"type": "m.room.message", "sender": self.roles[role]["sender_id"], "event_id": "$reply-" + role,
                     "content": {"body": "<cyberguard-report>" + json.dumps(self.report(role)) + "</cyberguard-report>"}}
            with patch.object(bridge, "_http", return_value={"chunk": [event], "end": "next"}):
                result = bridge.advance(self.job)
                self.job["bridge_state"] = result["bridge_state"]
        self.assertEqual(result["state"], "completed")
        self.assertEqual(len(result["runtime"]["worker_reports"]), 3)
        self.assertEqual(result["runtime"]["native_task_completion"], "not_attested")
        self.assertEqual(result["report"]["source_event_id"], "$reply-verifier")

    def test_fabricated_quote_and_wrong_job_fail_validation(self):
        for field, value in (("quote", "invented"), ("job_id", "other-job")):
            report = self.report("investigator")
            if field == "quote":
                report["findings"][0]["citations"][0]["quote"] = value
            else:
                report[field] = value
            with self.assertRaises(bridge.BridgeError):
                bridge._report("<cyberguard-report>" + json.dumps(report) + "</cyberguard-report>", self.job, "investigator")

    def test_unavailable_is_waiting_and_no_report(self):
        with patch.object(bridge, "_http", side_effect=bridge.BridgeError("AgentTeams is unavailable", "unavailable", True)):
            result = bridge.advance(self.job)
        self.assertEqual(result["state"], "waiting_backend")
        self.assertIsNone(result["report"])

    def test_configuration_change_fails_closed(self):
        self.job["bridge_state"] = {"binding": {"url": "different"}}
        with patch.object(bridge, "_http") as http:
            result = bridge.advance(self.job)
        self.assertEqual(result["state"], "failed")
        http.assert_not_called()

    def test_other_sender_cannot_complete_stage(self):
        self.job["bridge_state"] = {"cursor": "start", "request_event_id": "$request", "prepared_at": bridge.time.time()}
        event = {"type": "m.room.message", "sender": "@imposter:test",
                 "content": {"body": "<cyberguard-report>" + json.dumps(self.report("investigator")) + "</cyberguard-report>"}}
        with patch.object(bridge, "_http", return_value={"chunk": [event], "end": "next"}):
            result = bridge.advance(self.job)
        self.assertEqual(result["state"], "running")
        self.assertEqual(result["bridge_state"]["cursor"], "next")

    def test_size_deadline_and_malformed_events_fail_without_fabrication(self):
        self.job["materials"][0]["content"] = "x" * 70000
        with patch.object(bridge, "_http") as http:
            result = bridge.advance(self.job)
        self.assertEqual(result["runtime"]["error_code"], "input_too_large")
        http.assert_not_called()
        self.job["bridge_state"] = {"deadline_at": 1}
        with patch.object(bridge, "_http") as http:
            result = bridge.advance(self.job)
        self.assertEqual(result["runtime"]["error_code"], "job_timeout")
        http.assert_not_called()
        self.job["materials"][0]["content"] = "observed login"
        self.job["bridge_state"] = {"cursor": "start", "request_event_id": "$request", "prepared_at": bridge.time.time()}
        with patch.object(bridge, "_http", return_value={"chunk": "bad"}):
            result = bridge.advance(self.job)
        self.assertEqual(result["state"], "failed")
        self.assertIsNone(result["report"])

    def test_password_token_is_cached(self):
        cfg = bridge._config()
        cfg.update(MATRIX_TOKEN="", MATRIX_USER="admin", MATRIX_PASSWORD="private")
        bridge._TOKEN_CACHE.clear()
        with patch.object(bridge, "_http", return_value={"access_token": "private-token"}) as http:
            self.assertEqual(bridge._token(cfg), bridge._token(cfg))
            self.assertEqual(http.call_count, 1)

    def test_token_rotation_never_resends_prepared_transaction(self):
        self.job["bridge_state"] = {"cursor": "before", "token_fingerprint": "old-token-fingerprint"}
        with patch.object(bridge, "_http") as http:
            result = bridge.advance(self.job)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["runtime"]["error_code"], "matrix_credential_changed")
        http.assert_not_called()

    def test_native_reasoning_mentions_are_not_reports_and_edits_are(self):
        self.assertIsNone(bridge._report("I must answer inside <cyberguard-report>JSON</cyberguard-report>. Let me think.", self.job, "investigator"))
        body = "* <cyberguard-report>" + json.dumps(self.report("investigator")) + "</cyberguard-report>"
        self.assertEqual(bridge._report(body, self.job, "investigator")["role"], "investigator")

    def test_nonfinite_and_duplicate_report_fields_fail_closed(self):
        for suffix in (',"extra":NaN}', ',"extra":Infinity}', ',"role":"investigator"}'):
            raw = json.dumps(self.report("investigator"))[:-1] + suffix
            with self.assertRaises(bridge.BridgeError):
                bridge._report("<cyberguard-report>" + raw + "</cyberguard-report>", self.job, "investigator")


if __name__ == "__main__":
    unittest.main()
