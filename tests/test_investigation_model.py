"""No network model tests: contract fixtures do not represent live executions."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cyberguard_investigation.analysis import analyze_bundle
from cyberguard_investigation.evidence import load_bundle, make_bundle
from cyberguard_investigation.model_runner import EvidenceTools, run_model, validate_endpoint, ModelRunError, strict_json, digest, claim_attempt, atomic_write_text


class ModelRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = load_bundle(ROOT / "benchmark/investigation/cases/case-001.json")

    def response(self, name, arguments, *, usage=None):
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}, "finish_reason": "tool_calls"}],
                "usage": usage if usage is not None else {"prompt_tokens": 100, "completion_tokens": 30}}

    def run_case(self, transport, **kwargs):
        return run_model(self.bundle, endpoint="https://example.invalid/v1/chat/completions", model="contract-test", api_key="secret-test-value", output=Path(self.temp.name) / "out", transport=transport, attempts_ledger=Path(self.temp.name) / "attempts.sqlite", **kwargs)

    def test_actual_tool_loop_and_aggregate_usage(self):
        report = analyze_bundle(self.bundle)
        report.pop("method", None)
        report["mode"] = "single_agent"
        responses = iter([self.response("read_evidence_bundle", {}), self.response("submit_investigation_report", {"report": report})])
        result = self.run_case(lambda _: next(responses))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["usage"]["input_tokens"], 200)
        self.assertEqual(result["usage"]["output_tokens"], 60)
        self.assertEqual(result["usage"]["tool_calls"], 2)
        self.assertIsNone(result["usage"]["cost_usd"])
        self.assertEqual(result["report"]["mode"], "single_agent")

    def test_live_collection_forbidden_before_network(self):
        live = make_bundle([], provenance={"kind": "live_collection"})
        with self.assertRaises(ValueError):
            EvidenceTools(live, "run-1")

    def test_unknown_tool_and_submit_without_read_rejected(self):
        tools = EvidenceTools(self.bundle, "run-1")
        with self.assertRaises(ValueError):
            tools.call("shell", {"command": "anything"})
        with self.assertRaises(ValueError):
            tools.call("submit_investigation_report", {"report": {}})

    def test_endpoint_cannot_embed_credentials_or_redirect_to_http(self):
        for endpoint in ("http://example.com/v1", "https://user:pass@example.com/v1", "https://example.com/v1?key=secret"):
            with self.assertRaises(ValueError):
                validate_endpoint(endpoint)

    def test_usage_missing_stops_without_guessing_or_retry(self):
        calls = []
        def transport(payload):
            calls.append(payload)
            return self.response("read_evidence_bundle", {}, usage={})
        result = self.run_case(transport)
        self.assertEqual(result["failure"], "provider_usage_unavailable")
        self.assertIsNone(result["usage"]["input_tokens"])
        self.assertEqual(len(calls), 1)

    def test_output_budget_is_cumulative(self):
        calls = []
        def transport(payload):
            calls.append(payload)
            return self.response("read_evidence_bundle", {}, usage={"prompt_tokens": 100, "completion_tokens": 4500})
        result = self.run_case(transport)
        self.assertEqual(result["failure"], "provider_reported_budget_exceeded")
        self.assertEqual(result["usage"]["output_tokens"], 9000)
        self.assertEqual(calls[1]["max_tokens"], 3500)

    def test_zero_input_budget_sends_no_request(self):
        result = self.run_case(lambda _: self.fail("network call forbidden"), budget={"max_input_tokens": 0, "max_output_tokens": 8000, "max_tool_calls": 16})
        self.assertEqual(result["failure"], "budget_preflight_exhausted")

    def test_tool_budget_cannot_reset_between_rounds(self):
        result = self.run_case(lambda _: self.response("read_evidence_bundle", {}), budget={"max_input_tokens": 20000, "max_output_tokens": 8000, "max_tool_calls": 1})
        self.assertEqual(result["failure"], "tool_budget_exhausted")
        self.assertEqual(result["usage"]["tool_calls"], 1)

    def test_transport_errors_do_not_expose_credentials(self):
        def transport(_):
            raise RuntimeError("secret-test-value")
        result = self.run_case(transport)
        self.assertEqual(result["failure"], "runtime_error_details_withheld")
        self.assertIsNone(result["usage"]["input_tokens"])
        for path in (Path(self.temp.name) / "out").glob("*.json"):
            self.assertNotIn("secret-test-value", path.read_text(encoding="utf-8"))

    def test_exponent_overflow_rejected_in_entire_tree(self):
        with self.assertRaises(ValueError):
            strict_json('{"ignored":{"value":1e999}}')

    def test_nonfinite_response_cannot_leave_running_record(self):
        result = self.run_case(lambda _: {"extra": {"value": float("inf")}})
        self.assertEqual(result["status"], "failed")
        saved = json.loads((Path(self.temp.name) / "out/run-record.json").read_text())
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["failure"], "non_finite_or_malformed_response")
        json.loads((Path(self.temp.name) / "out/model-trace.json").read_text())

    def test_report_overflow_argument_cannot_poison_failure_serialization(self):
        report = analyze_bundle(self.bundle)
        report.pop("method", None)
        report["mode"] = "single_agent"
        report["unchecked_extra"] = float("inf")
        submitted = self.response("submit_investigation_report", {"report": report})
        submitted["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps({"report": report}).replace("Infinity", "1e999")
        responses = iter([self.response("read_evidence_bundle", {}), submitted])
        result = self.run_case(lambda _: next(responses))
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["report"])
        saved = json.loads((Path(self.temp.name) / "out/run-record.json").read_text())
        self.assertEqual(saved["status"], "failed")

    def test_escaped_credentials_are_redacted_before_json_encoding(self):
        secret = 'test"quoted\\credential'
        responses = iter([{"choices": [{"message": {"role": "assistant", "content": secret}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 20, "completion_tokens": 10}}])
        run_model(self.bundle, endpoint="https://example.invalid/v1", model="test", api_key=secret,
                  output=Path(self.temp.name) / "out", transport=lambda _: next(responses), attempts_ledger=Path(self.temp.name) / "ledger.sqlite")
        trace = json.loads((Path(self.temp.name) / "out/model-trace.json").read_text())
        self.assertEqual(trace[0]["response"]["choices"][0]["message"]["content"], "[REDACTED]")

    def gateway_fixtures(self):
        run = {"schema": "cyberguard-investigation-run/v1", "run_id": "run-1", "bundle_id": self.bundle["bundle_id"],
               "bundle_sha256": self.bundle["bundle_sha256"], "mode": "single_agent", "status": "prepared",
               "budget": {"max_input_tokens": 20000, "max_output_tokens": 8000, "max_tool_calls": 16},
               "tool_scope": ["read_evidence_bundle", "submit_investigation_report"], "created_at": "2026-09-17T00:00:00+00:00", "provenance": {}}
        run["run_sha256"] = digest(run)
        preflight = {"run": run, "reports": [], "tool_receipts": [], "tool_calls_used": 0}
        event = {"tool_call_id": "ITC-read", "run_id": "run-1", "bundle_sha256": self.bundle["bundle_sha256"],
                 "tool": "read_evidence_bundle", "sequence": 1, "credential_role": "reader", "recorded_at": "2026-09-17T00:00:00+00:00"}
        event["event_sha256"] = digest(event)
        read = {"run": run, "bundle": self.bundle, "tool_receipt": event}
        report = analyze_bundle(self.bundle)
        report.pop("method", None)
        report["mode"] = "single_agent"
        report_id = "IR-" + digest({"run_id": "run-1", "report": report})
        receipt = {**event, "tool_call_id": "ITC-submit", "tool": "submit_investigation_report", "sequence": 2, "credential_role": "reporter", "report_id": report_id}
        receipt["event_sha256"] = digest(receipt, "event_sha256")
        submit = {"report_id": report_id, "run_id": "run-1", "received_at": "2026-09-17T00:00:00+00:00", "report": report,
                  "tool_receipt": receipt, "validation": {"schema_and_citations": "valid", "actions_executed": False}}
        submit["submission_sha256"] = digest(submit)
        return preflight, read, submit, report

    def gateway_tools(self):
        return EvidenceTools(self.bundle, "run-1", gateway_url="http://127.0.0.1:9000", reader_token="reader", report_token="reporter")

    def test_gateway_valid_bound_receipts_and_submission_accepted(self):
        preflight, read, submit, report = self.gateway_fixtures()
        with patch("cyberguard_investigation.model_runner.http_json", side_effect=[preflight, read, submit]) as client:
            tools = self.gateway_tools()
            tools.call("read_evidence_bundle", {})
            tools.call("submit_investigation_report", {"report": report})
            self.assertEqual(tools.report, report)
            self.assertEqual(client.call_count, 3)

    def test_gateway_false_200_submission_not_completed(self):
        preflight, read, _, report = self.gateway_fixtures()
        with patch("cyberguard_investigation.model_runner.http_json", side_effect=[preflight, read, {"error": "rejected", "run_id": "OTHER"}]):
            tools = self.gateway_tools()
            tools.call("read_evidence_bundle", {})
            with self.assertRaises(ModelRunError):
                tools.call("submit_investigation_report", {"report": report})
            self.assertIsNone(tools.report)

    def test_gateway_read_receipt_wrong_binding_or_hash_rejected(self):
        for field, value in (("run_id", "OTHER"), ("sequence", 3), ("credential_role", "reporter"), ("event_sha256", "0" * 64)):
            with self.subTest(field=field):
                preflight, read, _, _ = self.gateway_fixtures()
                read["tool_receipt"][field] = value
                if field != "event_sha256":
                    read["tool_receipt"]["event_sha256"] = digest(read["tool_receipt"], "event_sha256")
                with patch("cyberguard_investigation.model_runner.http_json", side_effect=[preflight, read]):
                    with self.assertRaises(ModelRunError):
                        self.gateway_tools().call("read_evidence_bundle", {})

    def test_gateway_changed_report_or_receipt_hash_rejected(self):
        for variant in ("report", "submission_sha256", "receipt"):
            with self.subTest(variant=variant):
                preflight, read, submit, report = self.gateway_fixtures()
                submit = copy.deepcopy(submit)
                if variant == "report":
                    submit["report"]["unknowns"] = ["different report"]
                    submit["submission_sha256"] = digest(submit, "submission_sha256")
                elif variant == "receipt":
                    submit["tool_receipt"]["run_id"] = "OTHER"
                    submit["tool_receipt"]["event_sha256"] = digest(submit["tool_receipt"], "event_sha256")
                    submit["submission_sha256"] = digest(submit, "submission_sha256")
                else:
                    submit["submission_sha256"] = "0" * 64
                with patch("cyberguard_investigation.model_runner.http_json", side_effect=[preflight, read, submit]):
                    tools = self.gateway_tools()
                    tools.call("read_evidence_bundle", {})
                    with self.assertRaises(ModelRunError):
                        tools.call("submit_investigation_report", {"report": report})
                    self.assertIsNone(tools.report)

    def test_gateway_budget_handshake_precedes_any_model_request(self):
        preflight, _, _, _ = self.gateway_fixtures()
        preflight["run"]["budget"]["max_input_tokens"] = 1
        preflight["run"]["run_sha256"] = digest(preflight["run"], "run_sha256")
        with patch("cyberguard_investigation.model_runner.http_json", return_value=preflight):
            result = self.run_case(lambda _: self.fail("paid call forbidden"), run_id="run-1", gateway_url="http://127.0.0.1:9000", reader_token="reader", report_token="writer")
        self.assertEqual(result["failure"], "gateway_run_binding_mismatch")
        self.assertEqual(result["usage"]["input_tokens"], 0)

    def test_gateway_existing_run_cannot_reset_budget(self):
        preflight, _, _, _ = self.gateway_fixtures()
        preflight["tool_calls_used"] = 1
        with patch("cyberguard_investigation.model_runner.http_json", return_value=preflight):
            with self.assertRaises(ModelRunError):
                self.gateway_tools().prepare()

    def test_same_run_id_rejected_across_output_directories(self):
        ledger = Path(self.temp.name) / "shared/ledger.sqlite"
        def run(path):
            return run_model(self.bundle, endpoint="https://example.invalid/v1", model="test", api_key="secret-test-value", output=path,
                             run_id="same-run", attempts_ledger=ledger,
                             transport=lambda _: (_ for _ in ()).throw(ModelRunError("first_attempt_failed")))
        first = run(Path(self.temp.name) / "one/out")
        second = run(Path(self.temp.name) / "different-parent/out")
        self.assertEqual(first["failure"], "first_attempt_failed")
        self.assertEqual(second["failure"], "run_id_already_claimed_use_a_new_attempt_id")
        self.assertEqual(second["usage"]["input_tokens"], 0)

    def test_attempt_claim_is_atomic_for_local_concurrent_runners(self):
        ledger = Path(self.temp.name) / "ledger.sqlite"
        def claim(index):
            try:
                claim_attempt("concurrent-run", "protocol", Path(self.temp.name) / str(index), ledger)
                return "claimed"
            except ModelRunError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, (1, 2)))
        self.assertEqual(sorted(results), ["claimed", "rejected"])

    def test_transient_replace_permission_error_is_retried_locally(self):
        path = Path(self.temp.name) / "atomic.json"
        original = Path.replace
        calls = []
        def replace(source, target):
            calls.append(str(target))
            if len(calls) < 3:
                raise PermissionError("simulated transient file lock")
            return original(source, target)
        with patch.object(Path, "replace", replace), patch("cyberguard_investigation.model_runner.time.sleep") as pause:
            atomic_write_text(path, '{"status":"failed"}')
        self.assertEqual(json.loads(path.read_text())["status"], "failed")
        self.assertEqual(len(calls), 3)
        self.assertEqual(pause.call_count, 2)

    def test_permanent_persistence_failure_is_explicit_and_does_not_call_model(self):
        with patch.object(Path, "replace", side_effect=PermissionError("locked")), patch("cyberguard_investigation.model_runner.time.sleep"):
            result = self.run_case(lambda _: self.fail("model must not run after initial save failure"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"], "artifact_persistence_failed")
        self.assertEqual(result["persistence_status"], "failed_final_record_may_not_be_on_disk")
        self.assertEqual(result["usage"]["input_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
