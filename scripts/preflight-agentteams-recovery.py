#!/usr/bin/env python3
"""Offline native-history audit and room-call contract checks; never runs models."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

ROLES = ("response-planner", "endpoint-forensics", "recovery-verifier")


def strict_json(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate_json_key")
            value[key] = item
        return value
    return json.loads(text, object_pairs_hook=pairs)


def validate_room_request(value):
    """Observed TeamHarness roomflow contract, not a substitute for live discovery."""
    if not isinstance(value, dict) or value.get("action") != "create_task_room":
        raise ValueError("expected_create_task_room_object")
    if "payload" in value and not isinstance(value["payload"], dict):
        raise ValueError("payload_must_be_object_not_json_string")
    body = value.get("payload", value)
    if "invite" in body and (not isinstance(body["invite"], list) or
                            not all(isinstance(item, str) and item.startswith("@") and ":" in item for item in body["invite"])):
        raise ValueError("invite_must_be_array_of_matrix_ids")
    for name in ("projectId", "sourceRoomId"):
        if not isinstance(body.get(name), str) or not body[name]:
            raise ValueError("missing_" + name)
    return {"configuration_shape": "valid", "runtime_execution": "not_run"}


def audit(directory, target_run):
    result = {"scope": "offline_snapshot_audit_not_live_preflight", "target_run": target_run,
              "workers": {}, "runtime_readiness": "not_established"}
    for role in ROLES:
        path = Path(directory) / (role + "-history.json")
        if not path.exists():
            result["workers"][role] = {"missing_history": True}
            continue
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("history_too_large")
        raw = path.read_bytes()
        history = strict_json(raw)
        rows = history["rows"]
        contexts = defaultdict(list)
        calls = {}
        denied, room_errors, success_reads, submissions, task_actions = [], [], [], [], []
        target_times = [row["created_at"] for row in rows if row.get("kind") == "context_msg"
                        and re.search(r"调查任务：\s*" + re.escape(target_run) + r"\b", row.get("content", ""))]
        first_target = min(target_times) if target_times else None
        old_calls_after_start = []
        for row in rows:
            if row.get("kind") == "context_msg":
                key = (row.get("session_id"), hashlib.sha256(row.get("content", "").encode()).hexdigest())
                contexts[key].append({"seq": row["seq"], "created_at": row["created_at"], "dedup_key": row.get("dedup_key")})
            if row.get("kind") != "model_turn":
                continue
            for block in strict_json(row.get("blocks") or "[]"):
                if block.get("type") != "tool_call":
                    continue
                call_id = block.get("id")
                if call_id in calls:
                    continue  # Exported copies are not additional executions.
                try:
                    arguments = strict_json(block.get("input") or "{}")
                    parse_error = None
                except ValueError as exc:
                    arguments, parse_error = {}, str(exc)
                info = {"seq": row["seq"], "created_at": row["created_at"], "session_id": row.get("session_id"),
                        "tool": block.get("name"), "arguments": arguments, "parse_error": parse_error}
                calls[call_id] = info
                if (first_target and row["created_at"] >= first_target and isinstance(arguments, dict)
                        and isinstance(arguments.get("run_id"), str) and arguments["run_id"] != target_run):
                    old_calls_after_start.append({"seq": row["seq"], "call_id": call_id, "run_id": arguments["run_id"]})
        for row in rows:
            if row.get("kind") != "tool_result":
                continue
            name, content = row.get("name", ""), row.get("content", "")
            base = {"seq": row["seq"], "call_id": row.get("tool_call_id"), "session_id": row.get("session_id")}
            if "driver_policy_denied" in content:
                denied.append({**base, "tool": name})
            if name == "teamharness__roomflow" and "Input validation failed" in content:
                source = calls.get(row.get("tool_call_id"), {})
                room_errors.append({**base, "reason": "expected_array" if "type 'array'" in content else "expected_object" if "type 'object'" in content else "input_validation",
                                    "duplicate_key": source.get("parse_error") == "duplicate_json_key"})
            try:
                parsed = strict_json(content)
            except (ValueError, TypeError):
                continue
            if not isinstance(parsed, dict):
                continue
            if name.endswith("__read_investigation_evidence") and parsed.get("run", {}).get("run_id") == target_run and row.get("tool_state") == "success":
                receipt = parsed.get("tool_receipt", {})
                success_reads.append({**base, "receipt_id": receipt.get("tool_call_id"), "bundle_sha256": parsed.get("bundle", {}).get("bundle_sha256")})
            if name.endswith("__submit_investigation_report") and parsed.get("run_id") == target_run and parsed.get("validation", {}).get("schema_and_citations") == "valid":
                submissions.append({**base, "report_id": parsed.get("report_id")})
            if name in ("teamharness__taskflow", "teamharness__projectflow") and parsed.get("ok") is True:
                task_actions.append({**base, "action": parsed.get("action")})
        duplicates = [{"session_id": key[0], "content_sha256": key[1], "rows": value}
                      for key, value in contexts.items() if len(value) > 1]
        result["workers"][role] = {"export_sha256": hashlib.sha256(raw).hexdigest(), "row_count": len(rows),
            "duplicate_context_groups": duplicates, "driver_denials": denied, "room_argument_failures": room_errors,
            "successful_target_reads": success_reads, "accepted_target_submissions": submissions,
            "native_task_actions": task_actions, "other_run_tool_calls_after_target_start": old_calls_after_start,
            "other_run_absence_limit": "No matching exported call is not proof a private queue is empty."}
    result["all_three_roles_have_exported_read"] = all(result["workers"][r].get("successful_target_reads") for r in ROLES)
    return result


class ContractTests(unittest.TestCase):
    def test_arrays_are_accepted(self):
        self.assertEqual(validate_room_request({"action": "create_task_room", "projectId": "p", "sourceRoomId": "!r:local", "invite": ["@a:local", "@b:local"]})["configuration_shape"], "valid")

    def test_serialized_array_and_payload_are_rejected(self):
        for invite in ('["@a:local"]', "@a:local,@b:local"):
            with self.assertRaises(ValueError):
                validate_room_request({"action": "create_task_room", "projectId": "p", "sourceRoomId": "!r:local", "invite": invite})
        with self.assertRaises(ValueError):
            validate_room_request({"action": "create_task_room", "payload": '{"invite":[]}'})

    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            strict_json('{"invite":"a","invite":"b"}')

    def test_duplicate_context_is_distinct_from_old_queue_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{"seq": 1, "kind": "context_msg", "content": "调查任务：NEW", "session_id": "matrix:r", "created_at": "2026-09-17T00:00:00", "dedup_key": "a"},
                    {"seq": 2, "kind": "context_msg", "content": "调查任务：NEW", "session_id": "matrix:r", "created_at": "2026-09-17T00:00:01", "dedup_key": "b"}]
            Path(directory, "response-planner-history.json").write_text(json.dumps({"rows": rows}))
            result = audit(directory, "NEW")
            worker = result["workers"]["response-planner"]
            self.assertEqual(len(worker["duplicate_context_groups"]), 1)
            self.assertEqual(worker["other_run_tool_calls_after_target_start"], [])
            self.assertFalse(result["all_three_roles_have_exported_read"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-dir", type=Path)
    parser.add_argument("--target-run")
    parser.add_argument("--room-request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        unittest.main(argv=[__file__])
    elif args.room_request:
        print(json.dumps(validate_room_request(strict_json(args.room_request.read_text(encoding="utf-8")))))
    elif args.history_dir and args.target_run:
        result = audit(args.history_dir, args.target_run)
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
        else:
            print(text)
    else:
        parser.error("Choose --self-test, --room-request, or --history-dir with --target-run")
