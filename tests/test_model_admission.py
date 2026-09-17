"""Durable admission: real SQLite transactions across spawned processes, no models."""
import hashlib
import json
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyberguard_investigation.admission import AdmissionError, AdmissionLedger


HASH = hashlib.sha256(b"evidence").hexdigest()
BODY = hashlib.sha256(b"request").hexdigest()
TOKENS = {"leader": "private-leader-" + "a" * 40, "analyst": "private-analyst-" + "b" * 40}


def reserve_process(path, request_id, ready, release, result):
    try:
        ledger = AdmissionLedger(path)
        ready.put(True)
        release.wait(20)
        value = ledger.reserve("RUN-1", "leader", request_id, BODY, 30, 40)
        result.put({"forward": value["forward"], "status": value["status"]})
    except AdmissionError as exc:
        result.put({"error": exc.code})


def crash_after_reserve(path):
    AdmissionLedger(path).reserve("RUN-1", "leader", "CRASHED", BODY, 30, 40)
    os._exit(23)


def dispatch_or_close_process(path, action, ready, release, result):
    try:
        ledger = AdmissionLedger(path)
        ready.put(True)
        release.wait(20)
        if action == "close":
            value = ledger.close_run("RUN-1", "operator_stop")
            result.put({"action": action, "status": value["status"]})
        else:
            value = ledger.begin_dispatch("RUN-1", "REQ-1")
            result.put({"action": action, "dispatch": value["dispatch"]})
    except AdmissionError as exc:
        result.put({"action": action, "error": exc.code})


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "admission.sqlite"
        self.ledger = AdmissionLedger(self.path)
        self.limits = {"max_requests": 4, "max_input_tokens": 100, "max_output_tokens": 160}

    def create(self, **limits):
        return self.ledger.create_run("RUN-1", model="test-model", evidence_hash=HASH,
            limits={**self.limits, **limits}, role_credentials=TOKENS)

    def reserve(self, request_id="REQ-1", role="leader", input_reservation=30, output_reservation=40):
        return self.ledger.reserve("RUN-1", role, request_id, BODY, input_reservation, output_reservation)

    def assertCode(self, code, call):
        with self.assertRaises(AdmissionError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_role_private_credentials_and_no_plaintext_in_database(self):
        self.create()
        self.assertTrue(self.ledger.authenticate("RUN-1", "leader", TOKENS["leader"]))
        self.assertFalse(self.ledger.authenticate("RUN-1", "analyst", TOKENS["leader"]))
        self.assertFalse(self.ledger.authenticate("OTHER-RUN", "leader", TOKENS["leader"]))
        self.assertFalse(self.ledger.authenticate("RUN-1", "leader", "wrong"))
        self.assertFalse(self.ledger.authenticate("RUN-1", "missing", TOKENS["leader"]))
        raw = self.path.read_bytes()
        for token in TOKENS.values():
            self.assertNotIn(token.encode(), raw)
        summary = json.dumps(self.ledger.get_run("RUN-1"))
        self.assertNotIn("credential_hash", summary)
        self.assertNotIn("salt", summary)

    def test_run_binding_and_role_credentials_immutable_even_after_close(self):
        first = self.create()
        self.assertEqual(first, self.create())
        self.assertCode("run_binding_conflict", lambda: self.create(max_requests=5))
        self.assertCode("run_binding_conflict", lambda: self.ledger.create_run("RUN-1", model="different", evidence_hash=HASH,
            limits=self.limits, role_credentials=TOKENS))
        self.assertCode("run_role_binding_conflict", lambda: self.ledger.create_run("RUN-1", model="test-model", evidence_hash=HASH,
            limits=self.limits, role_credentials={**TOKENS, "leader": "x" * 40}))
        self.ledger.close_run("RUN-1")
        self.assertEqual(self.create()["status"], "closed")
        self.assertCode("run_closed", self.reserve)

    def test_reservation_replay_never_forwards_and_cannot_rebind(self):
        self.create()
        self.assertTrue(self.reserve()["forward"])
        duplicate = AdmissionLedger(self.path).reserve("RUN-1", "leader", "REQ-1", BODY, 30, 40)
        self.assertFalse(duplicate["forward"])
        self.assertEqual(duplicate["status"], "pending")
        self.assertEqual(self.ledger.get_run("RUN-1")["usage"]["requests"], 1)
        self.assertCode("request_binding_conflict", lambda: self.reserve(role="analyst"))
        self.assertCode("request_binding_conflict", lambda: self.reserve(output_reservation=41))
        self.assertCode("request_binding_conflict", lambda: self.ledger.reserve("RUN-1", "leader", "REQ-1", "0" * 64, 30, 40))

    def test_crash_pending_unknown_and_failed_do_not_release_reservations(self):
        self.create()
        self.reserve()
        restarted = AdmissionLedger(self.path)
        self.assertEqual(restarted.get_run("RUN-1")["usage"]["reserved_input"], 30)
        self.assertCode("concurrency_exhausted", lambda: restarted.reserve("RUN-1", "analyst", "REQ-2", BODY, 20, 20))
        for method in (restarted.mark_unknown, restarted.mark_failed):
            method("RUN-1", "REQ-1")
            state = restarted.get_run("RUN-1")["usage"]
            self.assertEqual((state["reserved_input"], state["reserved_output"], state["concurrency_used"]), (30, 40, 1))
            self.assertCode("concurrency_exhausted", lambda: restarted.reserve("RUN-1", "analyst", "REQ-2", BODY, 20, 20))

    def test_known_usage_settlement_refunds_only_unused_reservation(self):
        self.create()
        self.reserve()
        self.ledger.mark_unknown("RUN-1", "REQ-1")
        result = self.ledger.settle("RUN-1", "REQ-1", 11, 17)
        self.assertTrue(result["settled_now"])
        usage = result["run"]["usage"]
        self.assertEqual((usage["known_input"], usage["known_output"], usage["concurrency_used"]), (11, 17, 0))
        self.assertEqual(result["run"]["remaining"]["input_tokens"], 89)
        self.assertFalse(self.ledger.settle("RUN-1", "REQ-1", 11, 17)["settled_now"])
        self.assertCode("usage_settlement_conflict", lambda: self.ledger.settle("RUN-1", "REQ-1", 10, 17))
        self.assertCode("request_already_settled", lambda: self.ledger.mark_failed("RUN-1", "REQ-1"))
        self.assertTrue(self.reserve("REQ-2", role="analyst")["forward"])

    def test_global_request_and_token_limits_span_roles_and_restarts(self):
        self.create(max_requests=2)
        self.reserve()
        self.ledger.settle("RUN-1", "REQ-1", 30, 40)
        self.reserve("REQ-2", role="analyst")
        self.ledger.settle("RUN-1", "REQ-2", 30, 40)
        self.assertCode("request_budget_exhausted", lambda: self.reserve("REQ-3"))
        other = AdmissionLedger(Path(self.temp.name) / "tokens.sqlite")
        other.create_run("RUN-1", model="test-model", evidence_hash=HASH,
                         limits={**self.limits, "max_concurrency": 2}, role_credentials=TOKENS)
        other.reserve("RUN-1", "leader", "REQ-1", BODY, 60, 100)
        self.assertCode("token_budget_exhausted", lambda: other.reserve("RUN-1", "analyst", "REQ-2", BODY, 41, 30))
        self.assertCode("token_budget_exhausted", lambda: other.reserve("RUN-1", "analyst", "REQ-2", BODY, 20, 61))

    def test_overreservation_actual_usage_halts_and_is_not_clamped(self):
        self.create()
        self.reserve()
        result = self.ledger.settle("RUN-1", "REQ-1", 101, 200)
        self.assertEqual(result["run"]["status"], "halted")
        self.assertEqual(result["run"]["usage"]["known_output"], 200)
        self.assertEqual(result["run"]["remaining"]["output_tokens"], 0)
        self.assertCode("run_closed", lambda: self.reserve("REQ-2"))
        self.assertEqual(self.ledger.close_run("RUN-1")["status"], "halted")
        self.assertFalse(self.reserve()["forward"])

    def test_close_keeps_pending_and_allows_late_usage_accounting(self):
        self.create()
        self.reserve()
        self.ledger.close_run("RUN-1", "operator_stop")
        self.assertEqual(self.ledger.get_run("RUN-1")["usage"]["reserved_output"], 40)
        self.assertCode("run_closed", lambda: self.reserve("REQ-2"))
        settled = self.ledger.settle("RUN-1", "REQ-1", 20, 30)
        self.assertEqual(settled["run"]["status"], "closed")
        self.assertEqual(settled["run"]["usage"]["known_input"], 20)

    def test_invalid_numbers_do_not_change_ledger(self):
        self.create()
        for value in (-1, True, 1.5, float("nan"), 1_000_000_001):
            self.assertCode("invalid_input_reservation", lambda v=value: self.reserve(input_reservation=v))
        self.assertEqual(self.ledger.get_run("RUN-1")["usage"]["requests"], 0)
        self.reserve()
        self.assertCode("invalid_input_tokens", lambda: self.ledger.settle("RUN-1", "REQ-1", -1, 10))
        self.assertEqual(self.ledger.get_request("RUN-1", "REQ-1")["status"], "pending")

    def test_per_role_budget_stops_leader_and_preserves_other_role_capacity(self):
        self.create(max_requests_per_role={"leader": 1, "analyst": 2})
        self.reserve()
        self.ledger.settle("RUN-1", "REQ-1", 1, 1)
        self.assertCode("role_request_budget_exhausted", lambda: self.reserve("REQ-2"))
        self.assertTrue(self.reserve("REQ-2", role="analyst")["forward"])

    def concurrent(self, request_ids, target=reserve_process):
        context = multiprocessing.get_context("spawn")
        ready, result, release = context.Queue(), context.Queue(), context.Event()
        processes = [context.Process(target=target, args=(str(self.path), rid, ready, release, result)) for rid in request_ids]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                self.assertTrue(ready.get(timeout=20))
            release.set()
            values = [result.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(process.exitcode, 0)
            return values
        finally:
            release.set()
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            ready.close()
            result.close()

    def test_cross_process_duplicate_can_forward_only_once(self):
        self.create(max_concurrency=4)
        values = self.concurrent(["SAME"] * 4)
        self.assertEqual(sum(value.get("forward", False) for value in values), 1)
        self.assertEqual(self.ledger.get_run("RUN-1")["usage"]["requests"], 1)

    def test_cross_process_distinct_requests_cannot_race_concurrency_limit(self):
        self.create()
        values = self.concurrent(["REQ-" + str(i) for i in range(4)])
        self.assertEqual(sum(value.get("forward", False) for value in values), 1)
        self.assertEqual(sum(value.get("error") == "concurrency_exhausted" for value in values), 3)
        self.assertEqual(self.ledger.get_run("RUN-1")["usage"]["reserved_input"], 30)

    def test_cross_process_request_limit_and_token_limit_are_atomic(self):
        self.create(max_requests=2, max_concurrency=4)
        values = self.concurrent(["REQ-" + str(i) for i in range(4)])
        self.assertEqual(sum(value.get("forward", False) for value in values), 2)
        self.assertEqual(sum(value.get("error") == "request_budget_exhausted" for value in values), 2)
        self.path = Path(self.temp.name) / "token-race.sqlite"
        self.ledger = AdmissionLedger(self.path)
        self.create(max_concurrency=4)
        values = self.concurrent(["REQ-" + str(i) for i in range(4)])
        self.assertEqual(sum(value.get("forward", False) for value in values), 3)
        self.assertEqual(sum(value.get("error") == "token_budget_exhausted" for value in values), 1)
        self.assertEqual(self.ledger.get_run("RUN-1")["usage"]["charged_input"], 90)

    def test_abrupt_process_exit_does_not_refund_or_replay(self):
        self.create()
        process = multiprocessing.get_context("spawn").Process(target=crash_after_reserve, args=(str(self.path),))
        process.start()
        process.join(timeout=20)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            self.fail("crash simulation did not terminate")
        self.assertEqual(process.exitcode, 23)
        restarted = AdmissionLedger(self.path)
        duplicate = restarted.reserve("RUN-1", "leader", "CRASHED", BODY, 30, 40)
        self.assertFalse(duplicate["forward"])
        self.assertEqual(duplicate["status"], "pending")
        self.assertCode("concurrency_exhausted", lambda: restarted.reserve("RUN-1", "analyst", "OTHER", BODY, 10, 10))

    def test_close_before_dispatch_blocks_forwarding_and_keeps_reservation(self):
        self.create()
        self.assertTrue(self.reserve()["forward"])
        self.ledger.close_run("RUN-1")
        self.assertCode("run_closed", lambda: self.ledger.begin_dispatch("RUN-1", "REQ-1"))
        self.assertEqual(self.ledger.get_request("RUN-1", "REQ-1")["status"], "pending")
        self.assertEqual(self.ledger.get_run("RUN-1")["usage"]["reserved_output"], 40)

    def test_committed_dispatch_is_once_and_can_settle_after_close(self):
        self.create()
        self.reserve()
        committed = self.ledger.begin_dispatch("RUN-1", "REQ-1")
        self.assertTrue(committed["dispatch"])
        self.assertTrue(committed["forward"])
        self.assertEqual(committed["status"], "dispatched")
        duplicate = AdmissionLedger(self.path).begin_dispatch("RUN-1", "REQ-1")
        self.assertFalse(duplicate["dispatch"])
        self.assertFalse(duplicate["forward"])
        self.assertEqual(self.ledger.get_run("RUN-1")["usage"]["concurrency_used"], 1)
        self.ledger.close_run("RUN-1")
        self.assertCode("run_closed", lambda: self.ledger.begin_dispatch("RUN-1", "REQ-1"))
        settled = self.ledger.settle("RUN-1", "REQ-1", 21, 31)
        self.assertEqual(settled["run"]["status"], "closed")
        self.assertEqual(settled["run"]["usage"]["known_output"], 31)

    def test_unknown_failed_and_settled_requests_cannot_dispatch(self):
        self.create()
        self.reserve()
        self.ledger.mark_unknown("RUN-1", "REQ-1")
        self.assertCode("request_not_pending", lambda: self.ledger.begin_dispatch("RUN-1", "REQ-1"))
        self.ledger.mark_failed("RUN-1", "REQ-1")
        self.assertCode("request_not_pending", lambda: self.ledger.begin_dispatch("RUN-1", "REQ-1"))
        self.ledger.settle("RUN-1", "REQ-1", 10, 10)
        self.assertCode("request_not_pending", lambda: self.ledger.begin_dispatch("RUN-1", "REQ-1"))

    def test_cross_process_dispatch_can_commit_only_once(self):
        self.create()
        self.reserve()
        values = self.concurrent(["dispatch"] * 4, target=dispatch_or_close_process)
        self.assertEqual(sum(value.get("dispatch", False) for value in values), 1)
        self.assertTrue(all("dispatch" in value for value in values))
        self.assertEqual(self.ledger.get_request("RUN-1", "REQ-1")["status"], "dispatched")

    def test_cross_process_close_and_dispatch_have_serial_order(self):
        self.create()
        self.reserve()
        values = self.concurrent(["close", "dispatch"], target=dispatch_or_close_process)
        closed = next(value for value in values if value["action"] == "close")
        dispatch = next(value for value in values if value["action"] == "dispatch")
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(self.ledger.get_run("RUN-1")["status"], "closed")
        if dispatch.get("dispatch"):
            self.assertEqual(self.ledger.get_request("RUN-1", "REQ-1")["status"], "dispatched")
        else:
            self.assertEqual(dispatch.get("error"), "run_closed")
            self.assertEqual(self.ledger.get_request("RUN-1", "REQ-1")["status"], "pending")
        self.assertCode("run_closed", lambda: self.ledger.begin_dispatch("RUN-1", "REQ-1"))


if __name__ == "__main__":
    unittest.main()
