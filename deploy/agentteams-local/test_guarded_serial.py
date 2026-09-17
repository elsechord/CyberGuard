"""Exercise serial orchestration with fake HTTP/Docker only; no live credentials."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("guarded_serial", Path(__file__).with_name("run-guarded-serial.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ROLES = ("investigator", "planner", "verifier")


class SerialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plan_dir = Path(self.tmp.name) / "plan"
        self.plan_dir.mkdir()
        self.out = Path(self.tmp.name) / "out"
        self.plan = {"run_id": "RUN-TEST", "team": "cg-test", "roles": {
            role: {"worker": "cg-test-" + role, "model_alias": role + "-model"} for role in ROLES}}
        (self.plan_dir / "manifest.json").write_text(json.dumps(self.plan))
        self.config = {"run_id": "RUN-TEST", "evidence_hash": "a" * 64, "admin_token": "fake-admin"}
        self.sent, self.slept, self.closed = [], [], False
        self.old_usage = 0
        self.old_reports = False
        self.reports_fail = False
        self.closed_during_stage = False
        self.zero_role_usage = False
        self.new_denial = False
        self.sleep_failure = False
        self.drain_once = False
        self.poll = lambda seconds: (_ for _ in ()).throw(AssertionError("Unexpected polling"))

    def open(self, request, timeout):
        url = request.full_url
        if url.endswith("/admin/close"):
            self.closed = True
            result = {"armed": False, "run": {"status": "closed"}}
        elif url.endswith("/admin/status"):
            active = not (self.closed_during_stage and self.sent)
            result = {"armed": active, "denials": {"test_denial": 1} if self.new_denial and self.sent else {},
                "run": {"run_id": "RUN-TEST", "evidence_hash": "a" * 64,
                    "status": "open" if active else "closed",
                    "usage": {"requests": self.old_usage + len(self.sent), "concurrency_used": 0},
                    "requests_by_role": {} if self.zero_role_usage else {role: 2 for role in self.sent}}}
            if self.drain_once and self.slept:
                result["run"]["usage"]["concurrency_used"] = 1
                self.drain_once = False
        elif url.endswith("/reports"):
            if self.reports_fail:
                raise OSError("fake read failure")
            rows = [{"report_id": role + "-report", "run_id": "RUN-TEST", "report": {"bundle_sha256": "a" * 64}}
                    for role in self.sent]
            result = {"reports": [{"report_id": "old"}] if self.old_reports else rows,
                "tool_calls_used": len(rows), "tool_receipts": [],
                "run": {"run_id": "RUN-TEST", "mode": "multi_agent", "bundle_sha256": "a" * 64}}
        elif url.endswith("/login"):
            result = {"access_token": "fake-matrix"}
        elif "/send/m.room.message/" in url:
            prompt = json.loads(request.data)["body"]
            role = next(role for role in ROLES if "role " + role + ";" in prompt)
            self.sent.append(role)
            result = {"event_id": "event-" + role}
        else:
            raise AssertionError("Unexpected URL; no actual request allowed")
        return io.BytesIO(json.dumps(result).encode())

    def docker(self, command, **kwargs):
        if "sleep" in command:
            self.slept.append(command[-1])
            if kwargs.get("check") and self.sleep_failure:
                raise RuntimeError("fake sleep failure")
            return SimpleNamespace(returncode=1 if self.sleep_failure else 0)
        if "workers" in command:
            rows = [{"name": entry["worker"], "model": entry["model_alias"], "state": "Running",
                     "roomID": "!" + role, "matrixUserID": "@" + role} for role, entry in self.plan["roles"].items()]
            return SimpleNamespace(stdout=json.dumps({"workers": rows}), returncode=0)
        raise AssertionError("Unexpected subprocess; no actual Docker allowed")

    def run_main(self):
        read = Path.read_text
        config = self.config
        def read_text(path, *args, **kwargs):
            if path.name == "model-guard-config.json":
                return json.dumps(config)
            return read(path, *args, **kwargs)
        with patch.object(sys, "argv", ["serial", "--plan", str(self.plan_dir), "--out", str(self.out), "--execute"]), \
             patch.object(Path, "read_text", read_text), \
             patch.object(module, "env", return_value={"CYBERGUARD_API_TOKEN": "fake-reader", "AGENTTEAMS_ADMIN_USER": "fake", "AGENTTEAMS_ADMIN_PASSWORD": "fake"}), \
             patch.object(module.urllib.request, "build_opener", return_value=SimpleNamespace(open=self.open)), \
             patch.object(module.subprocess, "run", side_effect=self.docker), \
             patch.object(module.time, "sleep", side_effect=self.poll), \
             patch("sys.stdout", new_callable=io.StringIO):
            return module.main()

    def assert_stopped(self):
        self.assertTrue(self.closed)
        self.assertEqual(set(self.slept), {entry["worker"] for entry in self.plan["roles"].values()})

    def test_existing_output_closes_without_overwriting_previous_attempt(self):
        self.out.mkdir()
        prior = self.out / "serial-result.json"
        prior.write_text("previous attempt")
        self.assertEqual(self.run_main(), 1)
        self.assert_stopped()
        self.assertEqual(prior.read_text(), "previous attempt")
        self.assertEqual(self.sent, [])

    def test_failed_initial_gateway_read_still_closes_and_sleeps(self):
        self.reports_fail = True
        self.assertEqual(self.run_main(), 1)
        self.assert_stopped()
        self.assertEqual(self.sent, [])

    def test_existing_reports_or_model_usage_refuse_reuse_and_close(self):
        for attribute in ("old_usage", "old_reports"):
            with self.subTest(attribute=attribute):
                setattr(self, attribute, 1)
                self.assertEqual(self.run_main(), 1)
                self.assert_stopped()
                self.assertEqual(self.sent, [])
                setattr(self, attribute, 0)

    def test_closed_guard_prevents_accepting_simultaneously_available_report(self):
        self.closed_during_stage = True
        self.assertEqual(self.run_main(), 1)
        self.assert_stopped()
        result = json.loads((self.out / "serial-result.json").read_text())
        self.assertEqual(result["stages"][0]["status"], "sent")
        self.assertFalse(result["acceptance"]["completed"])

    def test_new_admission_denial_stops_before_report_acceptance(self):
        self.new_denial = True
        self.assertEqual(self.run_main(), 1)
        self.assert_stopped()
        self.assertEqual(self.sent, ["investigator"])

    def test_report_without_role_model_request_is_rejected(self):
        self.zero_role_usage = True
        self.assertEqual(self.run_main(), 1)
        self.assert_stopped()
        self.assertEqual(self.sent, ["investigator"])

    def test_three_reports_are_observations_not_completed_role_attestation(self):
        self.assertEqual(self.run_main(), 0)
        self.assert_stopped()
        result = json.loads((self.out / "serial-result.json").read_text())
        self.assertEqual(self.sent, list(ROLES))
        self.assertFalse(result["acceptance"]["completed"])
        self.assertEqual(result["acceptance"]["status"], "pending_native_review")
        for stage in result["stages"]:
            self.assertEqual(stage["role_attribution"], "not_attested")
            self.assertEqual(stage["tool_success"], "not_attested")
            self.assertFalse(stage["completed"])

    def test_sleep_failure_marks_cleanup_incomplete(self):
        self.sleep_failure = True
        self.assertEqual(self.run_main(), 1)
        self.assert_stopped()
        result = json.loads((self.out / "serial-result.json").read_text())
        self.assertEqual(result["status"], "incomplete_cleanup_failed")

    def test_sleep_does_not_start_next_role_before_in_flight_call_drains(self):
        self.drain_once = True
        polls = []
        def wait(seconds):
            self.assertEqual(self.sent, ["investigator"])
            polls.append(seconds)
        self.poll = wait
        self.assertEqual(self.run_main(), 0)
        self.assert_stopped()
        self.assertEqual(polls, [1])

    def test_redirects_are_not_followed(self):
        self.assertIsNone(module.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid"))


if __name__ == "__main__":
    unittest.main()
