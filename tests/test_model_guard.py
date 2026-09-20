"""Exercise the actual HTTP boundary without paid model calls."""
import copy
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from cyberguard_investigation.model_guard import create_app, GuardError, sanitized
from cyberguard_investigation.admission import AdmissionError


def configuration():
    return {"run_id": "GUARD-TEST-001", "model": "bound-model", "evidence_hash": "a" * 64,
        "upstream_endpoint": "https://model.invalid/v1/chat/completions", "upstream_key": "u" * 40,
        "admin_token": "a" * 40, "roles": {"investigator": {"token": "i" * 40, "model_alias": "investigate", "allowed_tools": ["read"]},
        "verifier": {"token": "v" * 40, "model_alias": "verify", "allowed_tools": ["read"]}},
        "limits": {"max_requests": 3, "max_requests_per_role": 2, "max_input_tokens": 20000,
                   "max_output_tokens": 8000, "max_concurrency": 1}, "max_output_per_request": 2000}


def reply(payload, *, usage=None):
    return {"id": "provider-actual-id", "created": 1, "model": "bound-model", "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "observed answer"}, "finish_reason": "stop"}],
        "usage": usage if usage is not None else {"prompt_tokens": 80, "completion_tokens": 12}}


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = configuration()
        self.calls = []

    def make(self, transport=None):
        def default_transport(endpoint, key, payload, timeout):
            self.calls.append(copy.deepcopy(payload))
            return reply(payload)
        self.app = create_app(self.config, self.temp.name, transport=transport or default_transport)
        self.client = TestClient(self.app)
        return self.client

    def arm(self):
        result = self.client.post("/admin/arm", headers={"Authorization": "Bearer " + self.config["admin_token"]})
        self.assertEqual(result.status_code, 200)

    def post(self, **changes):
        body = {"model": "investigate", "messages": [{"role": "user", "content": "exercise only"}], **changes}
        return self.client.post("/v1/chat/completions", headers={"Authorization": "Bearer " + "i" * 40}, json=body)

    def test_disarmed_wrong_role_and_wrong_model_do_not_forward(self):
        self.make()
        self.assertEqual(self.post().json()["error"]["code"], "guard_not_armed")
        self.arm()
        self.assertEqual(self.post(model="other-model").json()["error"]["code"], "model_not_bound")
        self.assertEqual(self.client.post("/v1/chat/completions", json={}).status_code, 401)
        self.assertEqual(self.calls, [])

    def test_native_runtime_owns_tool_policy_but_budget_and_identity_still_apply(self):
        self.config['tool_policy'] = 'runtime'
        for role in self.config['roles'].values():
            role.pop('allowed_tools')
        self.make()
        self.arm()
        tools = [{'type': 'function', 'function': {'name': 'teamharness_projectflow', 'parameters': {'type': 'object'}}}]
        self.assertEqual(self.post(tools=tools).status_code, 200)
        self.assertEqual(self.post(model='wrong', tools=tools).status_code, 400)
        self.assertEqual(len(self.calls), 1)

    def test_real_http_normalization_and_duplicate_never_forward_twice(self):
        self.make()
        self.arm()
        result = self.post(max_tokens=999999)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.calls[0]["max_tokens"], 2000)
        self.assertEqual(self.calls[0]["model"], "bound-model")
        self.assertFalse(self.calls[0]["stream"])
        self.assertEqual(self.post(max_tokens=999999).json()["error"]["code"], "duplicate_request_not_forwarded")
        self.assertEqual(len(self.calls), 1)
        record = self.app.state.guard.ledger.get_run(self.config["run_id"])
        self.assertEqual(record["usage"]["known_input"], 80)

    def test_stream_tool_calls_and_usage_emitted_after_settlement(self):
        def transport(*args):
            result = reply(args[2])
            result["choices"][0] = {"index": 0, "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "call-one", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
                "finish_reason": "tool_calls"}
            return result
        self.make(transport)
        self.arm()
        result = self.post(stream=True, stream_options={"include_usage": True},
                           tools=[{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}])
        self.assertEqual(result.status_code, 200)
        frames = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
        self.assertEqual(frames[0]["choices"][0]["delta"]["tool_calls"][0]["index"], 0)
        self.assertEqual(frames[-1]["usage"]["completion_tokens"], 12)
        self.assertEqual(self.app.state.guard.snapshot()["run"]["usage"]["concurrency_used"], 0)

    def test_unknown_usage_closes_run_and_preserves_reservation(self):
        self.make(lambda *args: reply(args[2], usage={}))
        self.arm()
        result = self.post()
        self.assertEqual(result.json()["error"]["code"], "provider_usage_unknown")
        state = self.app.state.guard.snapshot()["run"]
        self.assertEqual(state["status"], "closed")
        self.assertGreater(state["usage"]["reserved_input"], 0)
        self.assertEqual(state["usage"]["known_input"], 0)
        self.assertEqual(state["usage"]["concurrency_used"], 1)

    def test_excess_provider_usage_retained_and_halts(self):
        self.make(lambda *args: reply(args[2], usage={"prompt_tokens": 90000, "completion_tokens": 5}))
        self.arm()
        self.assertEqual(self.post().json()["error"]["code"], "provider_exceeded_reservation")
        state = self.app.state.guard.snapshot()["run"]
        self.assertEqual(state["status"], "halted")
        self.assertEqual(state["usage"]["known_input"], 90000)

    def test_provider_error_secrets_are_not_exposed_or_retried(self):
        def failing(*args):
            self.calls.append(True)
            raise RuntimeError(self.config["upstream_key"])
        self.make(failing)
        self.arm()
        result = self.post()
        self.assertEqual(result.status_code, 400)
        self.assertNotIn(self.config["upstream_key"], result.text)
        traces = list(Path(self.temp.name).glob("*.json"))
        self.assertTrue(traces)
        self.assertNotIn(self.config["upstream_key"], "".join(p.read_text() for p in traces))
        self.assertEqual(len(self.calls), 1)

    def test_parallel_request_rejected_while_first_is_in_flight(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            self.calls.append(True)
            entered.set()
            release.wait(5)
            return reply(args[2])
        self.make(slow)
        self.arm()
        first = []
        thread = threading.Thread(target=lambda: first.append(self.post()))
        thread.start()
        self.assertTrue(entered.wait(3))
        try:
            result = self.post(messages=[{"role": "user", "content": "different concurrent request"}])
            self.assertEqual(result.json()["error"]["code"], "concurrency_exhausted")
            self.assertEqual(len(self.calls), 1)
        finally:
            release.set()
            thread.join(5)
        self.assertEqual(first[0].status_code, 200)

    def test_restart_disarms_and_preserves_duplicate_ledger(self):
        self.make()
        self.arm()
        self.assertEqual(self.post().status_code, 200)
        self.make()
        self.assertEqual(self.post().json()["error"]["code"], "guard_not_armed")
        self.arm()
        self.assertEqual(self.post().json()["error"]["code"], "duplicate_request_not_forwarded")
        self.assertEqual(len(self.calls), 1)
        self.config["max_output_per_request"] = 1000
        with self.assertRaisesRegex(ValueError, "configuration changed"):
            self.make()

    def test_close_before_dispatch_does_not_call_provider(self):
        self.make()
        self.arm()
        guard = self.app.state.guard
        identifier, payload, _ = guard.prepare("investigator", {"model": "investigate", "messages": [{"role": "user", "content": "hello"}]})
        self.client.post("/admin/close", headers={"Authorization": "Bearer " + self.config["admin_token"]})
        with self.assertRaisesRegex(Exception, "run_stopped_before_dispatch"):
            guard.execute("investigator", identifier, payload)
        self.assertEqual(self.calls, [])

    def test_repeated_structured_tool_failure_closes_run(self):
        self.make()
        self.arm()
        messages = []
        for number in (1, 2):
            messages += [{"role": "assistant", "tool_calls": [{"id": str(number), "function": {"name": "bad_tool", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": str(number), "content": '{"error":{"code":"invalid_arguments"}}'}]
        self.assertEqual(self.post(messages=messages).json()["error"]["code"], "repeated_structured_tool_failure")
        self.assertEqual(self.calls, [])

    def test_tool_allowlist_rejects_unexpected_shell_without_provider(self):
        self.config["roles"]["investigator"]["allowed_tools"] = ["read"]
        self.make()
        self.arm()
        result = self.post(tools=[{"type": "function", "function": {"name": "execute_shell_command", "parameters": {}}}])
        self.assertEqual(result.json()["error"]["code"], "tool_definition_not_allowed")
        self.assertEqual(self.calls, [])

    def test_tool_allowlist_denial_records_offending_names_durably(self):
        self.config["roles"]["investigator"]["allowed_tools"] = ["read"]
        self.make()
        self.arm()
        tools = [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}},
                 {"type": "function", "function": {"name": "mcp-other__write_evidence", "parameters": {"type": "object"}}},
                 {"type": "function", "function": {"name": "Skill", "parameters": {"type": "object"}}}]
        result = self.post(tools=tools)
        self.assertEqual(result.json()["error"]["code"], "tool_definition_not_allowed")
        # The HTTP error body must not leak the diagnostic or any schema content.
        self.assertNotIn("mcp-other__write_evidence", result.text)
        snapshot = self.app.state.guard.snapshot()
        self.assertEqual(snapshot["denials"]["tool_definition_not_allowed"], 1)
        self.assertEqual(len(snapshot["denial_details"]), 1)
        detail = snapshot["denial_details"][0]
        self.assertEqual(detail["code"], "tool_definition_not_allowed")
        self.assertEqual(detail["role"], "investigator")
        self.assertEqual(detail["offending_tool_names"], ["Skill", "mcp-other__write_evidence"])
        self.assertEqual(detail["requested_tool_names"], ["Skill", "mcp-other__write_evidence", "read"])
        self.assertEqual(detail["allowed_tool_names"], ["read"])
        self.assertEqual(detail["request_tool_count"], 3)
        self.assertEqual(detail["malformed_tool_definitions"], 0)
        durable = list(Path(self.temp.name).glob("tool-denial-*.json"))
        self.assertEqual(len(durable), 1)
        recorded = json.loads(durable[0].read_text())
        self.assertEqual(recorded["offending_tool_names"], detail["offending_tool_names"])
        self.assertNotIn(self.config["upstream_key"], durable[0].read_text())
        self.assertEqual(self.calls, [])

    def test_tool_allowlist_denial_counts_malformed_definitions(self):
        self.make()
        self.arm()
        result = self.post(tools=[{"type": "function", "function": {"parameters": {}}},
                                  {"type": "function", "function": {"name": "read"}},
                                  "not-a-dict"])
        self.assertEqual(result.json()["error"]["code"], "tool_definition_not_allowed")
        detail = self.app.state.guard.snapshot()["denial_details"][0]
        self.assertEqual(detail["malformed_tool_definitions"], 2)
        self.assertEqual(detail["requested_tool_names"], ["read"])
        self.assertEqual(detail["request_tool_count"], 3)
        self.assertEqual(self.calls, [])

    def test_declaration_records_nonconforming_tool_names(self):
        self.make()
        result = self.post(tools=[{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}},
                                  {"type": "function", "function": {"name": "mcp.legacy/read_evidence", "parameters": {}}},
                                  {"type": "function", "function": {"parameters": {}}}])
        self.assertEqual(result.json()["error"]["code"], "guard_not_armed")
        artifact = Path(self.temp.name) / "declaration-investigator.json"
        observed = json.loads(artifact.read_text())
        self.assertEqual([tool["name"] for tool in observed["tools"]], ["read"])
        self.assertIn("'mcp.legacy/read_evidence'", observed["nonconforming_tool_names"])
        self.assertIn("malformed_name:None", observed["nonconforming_tool_names"])
        self.assertEqual(self.calls, [])

    def test_close_during_last_trace_write_blocks_dispatch(self):
        self.make()
        self.arm()
        guard = self.app.state.guard
        original = guard._write_trace
        def close_before_commit(identifier, record):
            original(identifier, record)
            if record["upstream_status"] == "ready_to_dispatch":
                guard.ledger.close_run(guard.run_id, "test_close")
        with patch.object(guard, "_write_trace", side_effect=close_before_commit):
            self.assertEqual(self.post().status_code, 400)
        self.assertEqual(self.calls, [])

    def test_storage_error_during_failure_still_disarms(self):
        def failing(*args):
            self.calls.append(True)
            raise GuardError("provider_usage_unknown")
        self.make(failing)
        self.arm()
        guard = self.app.state.guard
        with patch.object(guard.ledger, "mark_unknown", side_effect=AdmissionError("ledger_unavailable")), patch.object(guard.ledger, "close_run", side_effect=AdmissionError("ledger_unavailable")):
            self.assertEqual(self.post().status_code, 400)
        self.assertFalse(guard.armed)
        self.assertEqual(self.post(messages=[{"role": "user", "content": "another"}]).json()["error"]["code"], "guard_not_armed")
        self.assertEqual(len(self.calls), 1)

    def test_native_policy_errors_stop_before_provider(self):
        self.make()
        self.arm()
        messages = []
        for number in (1, 2):
            messages += [{"role": "assistant", "tool_calls": [{"id": str(number), "function": {"name": "read", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": str(number), "content": '{"ok":false,"type":"driver_policy_denied"}'}]
        self.assertEqual(self.post(messages=messages).json()["error"]["code"], "repeated_structured_tool_failure")
        self.assertEqual(self.calls, [])

    def test_malformed_provider_tool_calls_do_not_escape_sse_error_handler(self):
        def malformed(*args):
            result = reply(args[2])
            result["choices"][0]["message"]["tool_calls"] = ["bad"]
            return result
        self.make(malformed)
        self.arm()
        result = self.post(stream=True)
        self.assertEqual(result.json()["error"]["code"], "provider_message_invalid")
        self.assertFalse(self.app.state.guard.armed)
        self.assertEqual(self.app.state.guard.snapshot()["run"]["usage"]["known_input"], 80)

    def test_nested_json_credential_redaction(self):
        secret = 'test"quoted\\credential'
        result = sanitized({"content": json.dumps({"header": secret})}, [secret])
        self.assertEqual(json.loads(result["content"])["header"], "[REDACTED]")

    def test_provider_cannot_request_undeclared_shell(self):
        def transport(*args):
            result = reply(args[2])
            result["choices"][0]["message"]["tool_calls"] = [{"id": "x", "type": "function", "function": {"name": "execute_shell_command", "arguments": "{}"}}]
            return result
        self.make(transport)
        self.arm()
        result = self.post()
        self.assertEqual(result.json()["error"]["code"], "provider_requested_undeclared_tool")
        self.assertFalse(self.app.state.guard.armed)

    def test_disarmed_probe_retains_only_schema_identity_not_messages(self):
        self.make()
        result = self.post(messages=[{"role": "user", "content": "PRIVATE-CONTEXT"}],
                           tools=[{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}])
        self.assertEqual(result.json()["error"]["code"], "guard_not_armed")
        artifact = Path(self.temp.name) / "declaration-investigator.json"
        self.assertNotIn("PRIVATE-CONTEXT", artifact.read_text())
        self.assertEqual(json.loads(artifact.read_text())["tools"][0]["name"], "read")
        self.assertEqual(self.calls, [])

    def test_scalar_or_object_history_tool_calls_rejected_before_reservation(self):
        self.make()
        self.arm()
        for calls in (3, 0, True, False, "call", "", {}, {"id": "call-one"}):
            with self.subTest(calls=calls):
                result = self.post(messages=[{"role": "assistant", "tool_calls": calls}])
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json()["error"]["code"], "invalid_messages")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.app.state.guard.snapshot()["run"]["usage"]["requests"], 0)

    def test_invalid_history_call_ids_and_functions_rejected_before_reservation(self):
        self.make()
        self.arm()
        valid = {"id": "call-one", "type": "function", "function": {"name": "read", "arguments": "{}"}}
        invalid = [None, 3, [], "bad", *({**valid, "id": value} for value in (None, [], {}, 1, False, "", " ")),
                   {**valid, "function": []}, {**valid, "function": {"name": [], "arguments": "{}"}},
                   {**valid, "function": {"name": "read", "arguments": {}}}]
        for call in invalid:
            with self.subTest(call=call):
                result = self.post(messages=[{"role": "assistant", "tool_calls": [call]}])
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json()["error"]["code"], "invalid_messages")
        result = self.post(messages=[{"role": "assistant", "tool_calls": [valid, valid]}])
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.app.state.guard.snapshot()["run"]["usage"]["requests"], 0)

    def test_invalid_tool_result_ids_cannot_escape_failure_detection(self):
        self.make()
        self.arm()
        for identifier in (None, [], {}, 3, False, "", " "):
            with self.subTest(identifier=identifier):
                result = self.post(messages=[{"role": "tool", "tool_call_id": identifier,
                                             "content": '{"ok":false,"type":"driver_policy_denied"}'}])
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json()["error"]["code"], "invalid_messages")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.app.state.guard.snapshot()["run"]["usage"]["requests"], 0)

    def test_null_history_tool_calls_remain_accepted(self):
        self.make()
        self.arm()
        result = self.post(messages=[{"role": "assistant", "content": "context", "tool_calls": None},
                                     {"role": "user", "content": "continue"}])
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(self.calls), 1)

    def test_container_model_and_role_return_validation_errors(self):
        self.make()
        self.arm()
        for model in ([], {}):
            with self.subTest(model=model):
                self.assertEqual(self.post(model=model).status_code, 400)
        for role in ([], {}, None):
            with self.subTest(role=role):
                result = self.post(messages=[{"role": role, "content": "test"}])
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json()["error"]["code"], "invalid_messages")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.app.state.guard.snapshot()["run"]["usage"]["requests"], 0)


if __name__ == "__main__":
    unittest.main()
