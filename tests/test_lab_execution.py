"""Black-box integration tests: actual HTTP, SQLite mutations, process restarts."""
import importlib.util
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from lab_support import LabStack, ROOT, http


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


identity = module("lab_identity", "services/lab-identity/server.py")
verifier = module("lab_verifier", "services/security-tool-gateway/app/lab_verification.py")
run_view = module("run_view", "services/security-tool-gateway/app/run_view.py")


class LostResponseProxy:
    """Forward the write, wait for its committed receipt, then drop the reply."""
    def __init__(self, stack):
        self.posts = 0
        self.lose_next = True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def forward(self, body=None):
                status, payload = http(stack.urls["identity"] + self.path, stack.tokens["admin"], body)
                if body is not None:
                    owner.posts += 1
                    if owner.lose_next:
                        owner.lose_next = False
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.close_connection = True
                        return
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self.forward()

            def do_POST(self):
                self.forward(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class IdentityTransactionTests(unittest.TestCase):
    def test_persistent_idempotency_binding_and_rollback_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.sqlite"
            store = identity.IdentityStore(path)
            request = dict(kind="disable", target="compromised-lab", action_id="ACT-one",
                           run_id="run-one", environment_id=store.environment_id)
            receipt = store.apply("ACT-one", request)
            self.assertFalse(store.access("compromised-lab"))
            self.assertTrue(store.access("control-lab"))
            store = identity.IdentityStore(path)
            self.assertEqual(store.apply("ACT-one", request), receipt)
            with self.assertRaises(identity.Conflict):
                store.apply("ACT-one", {**request, "run_id": "run-two"})
            with self.assertRaises(identity.Conflict):
                store.apply("ACT-two", {**request, "action_id": "ACT-two"})
            with self.assertRaises(ValueError):
                store.apply("ACT-one", {**request, "target": "control-lab"})
            with self.assertRaises(identity.Conflict):
                store.apply("ACT-one-rollback", {**request, "kind": "restore", "run_id": "run-two"})
            rollback = store.apply("ACT-one-rollback", {**request, "kind": "restore"})
            self.assertEqual(store.apply("ACT-one-rollback", {**request, "kind": "restore"}), rollback)
            # Replaying the old disable returns its original receipt, without disabling again.
            self.assertEqual(store.apply("ACT-one", request), receipt)
            self.assertTrue(store.access("compromised-lab"))


class LabExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stack = LabStack().__enter__()
        self.addCleanup(self.stack.__exit__, None, None, None)

    def proposed(self, run="lab-test-run"):
        status, action = self.stack.propose(run)
        self.assertEqual(status, 200, action)
        return action

    def execute(self, action):
        status, approval = self.stack.approve(action)
        self.assertEqual(status, 200, approval)
        status, result = self.stack.call(f'/actions/{action["action_id"]}/execute', {})
        self.assertEqual(status, 200, result)
        return result

    def verdict(self, action, run=None):
        status, payload = self.stack.verify(action, run)
        self.assertEqual(status, 200, payload)
        return payload["evidence"]["data"]["verdict"]

    def access(self, account="target"):
        return http(self.stack.urls["identity"] + "/access?nonce=testing123", self.stack.tokens[account])[0]

    def exported(self, run):
        status, payload = http(self.stack.urls["gateway"] + "/incidents/CG-LAB-001/runs/" + run, self.stack.tokens["gateway"])
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["export_sha256"], run_view.digest({k:v for k,v in payload.items() if k != "export_sha256"}))
        return payload

    def test_real_containment_independent_probes_and_approved_rollback(self):
        action = self.proposed()
        path = f'/actions/{action["action_id"]}'
        self.assertEqual(self.access(), 200)
        self.assertEqual(self.stack.call(path + "/execute", {})[0], 409)
        self.assertEqual(self.verdict(action), "inconclusive")
        result = self.execute(action)
        self.assertEqual(result["result"], "applied")
        self.assertEqual(result["verification_status"], "pending")
        self.assertEqual(self.access(), 403)
        self.assertEqual(self.access("control"), 200)
        self.assertEqual(self.verdict(action), "verified")
        exported = self.exported(action["run_id"])
        self.assertEqual(exported["audit_status"], "valid")
        self.assertEqual(exported["evidence_integrity"], "valid")
        self.assertEqual(exported["action_states"][0]["verification"], "verified")
        self.assertEqual(exported["provenance"]["agentteams_task"], "not_attested")
        self.assertEqual(self.verdict(action, "another-run"), "inconclusive")
        self.assertEqual(self.stack.call(path + "/execute", {})[1], result)
        self.assertEqual(self.stack.call(path + "/rollback", {})[0], 403)
        self.assertEqual(self.stack.call(path + "/rollback", {}, True)[1]["status"], "rolled_back")
        # The export must invalidate a green observation even before another probe.
        exported = self.exported(action["run_id"])
        self.assertEqual(exported["action_states"][0]["status"], "rolled_back")
        self.assertEqual(exported["action_states"][0]["verification"], "inconclusive")
        self.assertEqual(self.access(), 200)
        self.assertEqual(self.verdict(action), "inconclusive")
        self.assertEqual(self.stack.call(path + "/execute", {})[0], 409)
        self.assertTrue(self.stack.call("/audit/verify")[1]["valid"])

    def test_lost_receipt_reconciles_after_restart_without_reexecuting(self):
        proxy = LostResponseProxy(self.stack)
        self.addCleanup(proxy.close)
        self.stack.stop("executor")
        self.stack.overrides["executor"] = {"CYBERGUARD_LAB_URL": proxy.url}
        self.stack.start("executor")
        action = self.proposed()
        path = f'/actions/{action["action_id"]}'
        self.assertEqual(self.execute(action)["status"], "execution_unknown")
        self.assertEqual(self.access(), 403)  # External commit really happened.
        self.assertEqual(self.verdict(action), "inconclusive")
        for role in ("identity", "executor"):
            self.stack.stop(role)
            self.stack.start(role)
        result = self.stack.call(path + "/reconcile", {})[1]
        self.assertEqual(result["status"], "executed")
        self.assertEqual(proxy.posts, 1)
        self.assertEqual(self.verdict(action), "verified")
        proxy.lose_next = True
        self.assertEqual(self.stack.call(path + "/rollback", {}, True)[1]["status"], "rollback_unknown")
        self.assertEqual(self.access(), 200)
        self.assertEqual(self.stack.call(path + "/execute", {})[0], 409)
        self.assertEqual(self.verdict(action), "inconclusive")
        self.stack.stop("executor")
        self.stack.start("executor")
        self.assertEqual(self.stack.call(path + "/reconcile", {})[1]["status"], "rolled_back")
        self.assertEqual(proxy.posts, 2)

    def test_outage_and_missing_receipt_remain_unknown_without_retry(self):
        action = self.proposed()
        self.stack.stop("identity")
        self.assertEqual(self.execute(action)["status"], "execution_unknown")
        self.stack.start("identity")
        path = f'/actions/{action["action_id"]}'
        result = self.stack.call(path + "/execute", {})[1]
        self.assertEqual(result["status"], "execution_unknown")
        self.assertEqual(result["reconciliation"], "unresolved")
        self.assertEqual(self.access(), 200)
        self.assertEqual(self.verdict(action), "inconclusive")

    def test_probe_outage_and_wrong_credentials_cannot_pass(self):
        action = self.proposed()
        self.execute(action)
        self.stack.stop("identity")
        self.assertEqual(self.verdict(action), "inconclusive")
        self.stack.start("identity")
        self.stack.stop("gateway")
        self.stack.overrides["gateway"] = {"CYBERGUARD_LAB_TARGET_TOKEN": "invalid-credential"}
        self.stack.start("gateway")
        self.assertEqual(self.verdict(action), "inconclusive")

    def test_audit_receipt_without_current_external_effect_fails_verification(self):
        action = self.proposed()
        self.execute(action)
        # A separate administrator restores access. The executor still reports executed.
        request = {key: action[key] for key in ("target", "action_id", "run_id", "environment_id")}
        status, _ = http(self.stack.urls["identity"] + "/operations/" + action["action_id"] + "-rollback",
                         self.stack.tokens["admin"], {**request, "kind": "restore"})
        self.assertEqual(status, 200)
        self.assertEqual(self.verdict(action), "failed")

    def test_corrupted_audit_prevents_real_side_effect(self):
        action = self.proposed()
        self.stack.approve(action)
        path = self.stack.directory / "executor/actions.jsonl"
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["target"] = "tampered-target"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        status, _ = self.stack.call(f'/actions/{action["action_id"]}/execute', {})
        self.assertEqual(status, 409)
        self.assertEqual(self.access(), 200)
        self.assertEqual(self.verdict(action), "inconclusive")

    def test_simulated_execution_is_not_lab_evidence(self):
        self.stack.stop("executor")
        self.stack.overrides["executor"] = {"CYBERGUARD_EXECUTION_MODE": "simulation"}
        self.stack.start("executor")
        action = self.proposed()
        self.assertEqual(self.execute(action)["result"], "simulated_success")
        self.assertEqual(self.access(), 200)
        self.assertEqual(self.verdict(action), "inconclusive")

    def test_probe_rejects_wrong_nonce_even_if_access_status_matches(self):
        with patch.dict(os.environ, self.stack.environment("gateway")), patch.object(verifier, "read",
                return_value=(403, {"account": "compromised-lab", "allowed": False,
                    "reason": "account_disabled", "environment_id": "env-one", "nonce": "stale-nonce"})):
            with self.assertRaises(verifier.ProbeError):
                verifier.probe("compromised-lab", "CYBERGUARD_LAB_TARGET_TOKEN", "env-one")

    def test_export_separates_runs_detects_modified_evidence_and_fails_closed_on_audit_loss(self):
        first = self.proposed("run-first")
        self.execute(first)
        self.verdict(first)
        self.stack.call(f'/actions/{first["action_id"]}/rollback', {}, True)
        second = self.proposed("run-second")
        self.execute(second)
        self.verdict(second)
        self.verdict(second)  # A corrupted latest observation must not revive the older green one.
        one, two = self.exported("run-first"), self.exported("run-second")
        self.assertEqual({e["action_id"] for e in one["actions"]}, {first["action_id"]})
        self.assertEqual({e["run_id"] for e in two["evidence"]}, {"run-second"})
        self.assertEqual(two["action_states"][0]["verification"], "verified")
        path = self.stack.directory / "gateway/evidence.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[-1]["data"]["checks"][0]["allowed"] = True
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        changed = self.exported("run-second")
        self.assertEqual(changed["evidence_integrity"], "invalid")
        self.assertEqual(changed["action_states"][0]["verification"], "inconclusive")
        self.stack.stop("executor")
        lost = self.exported("run-first")
        self.assertEqual(lost["audit_status"], "unavailable")
        self.assertEqual(lost["action_states"], [])

    def test_conflicting_run_fields_rejected_before_collecting_evidence(self):
        status, _ = http(self.stack.urls["gateway"] + "/tools/recovery/metrics", self.stack.tokens["gateway"], {
            "incident_id": "CG-LAB-001", "scenario_id": "lab_identity", "run_id": "run-one",
            "arguments": {"run_id": "run-two", "action_id": "ACT-one"}})
        self.assertEqual(status, 422)
        self.assertFalse((self.stack.directory / "gateway/evidence.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
