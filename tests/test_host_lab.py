"""Integration tests require Linux /proc and real child processes; Windows skips."""
import os
import signal
import sys
import time
import unittest
from uuid import uuid4

from host_lab_support import HostLabStack, http
from test_lab_execution import LostResponseProxy


@unittest.skipUnless(sys.platform == "linux", "real process laboratory runs in Linux Docker")
class HostLabTests(unittest.TestCase):
    def setUp(self):
        self.stack = HostLabStack().__enter__()
        self.addCleanup(self.stack.__exit__, None, None, None)
        self.run_id = "TEST-" + uuid4().hex

    def proposal(self, kind, target):
        code, action = self.stack.propose_host(self.run_id, kind, target)
        self.assertEqual(code, 200, action)
        return action

    def execute(self, action):
        self.assertEqual(self.stack.approve(action)[0], 200)
        code, result = self.stack.call("/actions/" + action["action_id"] + "/execute", {})
        self.assertEqual(code, 200, result)
        return result

    def observation(self, action):
        code, result = self.stack.verify(action)
        self.assertEqual(code, 200, result)
        return result["evidence"]["data"]

    def test_partial_cleanup_recurs_complete_cleanup_verifies_and_control_survives(self):
        code, evidence = self.stack.collect(self.run_id)
        self.assertEqual(code, 200, evidence)
        self.assertEqual(evidence["evidence"]["execution"], "real")
        before = evidence["evidence"]["data"]
        target = next(p for p in before["processes"] if p["role"] == "compute")
        action = self.proposal("terminate_process", target["target_ref"])
        self.assertEqual(self.stack.call("/actions/" + action["action_id"] + "/execute", {})[0], 409)
        self.assertEqual(self.observation(action)["verdict"], "inconclusive")
        self.assertEqual(self.execute(action)["status"], "executed")
        result = self.observation(action)
        self.assertEqual(result["verdict"], "failed")
        restarted = next(p for p in result["checks"][-1]["processes"] if p["role"] == "compute")
        self.assertNotEqual(restarted["target_ref"], target["target_ref"])
        self.assertTrue(result["layers"]["control_workload_progressing"])
        _, current = self.stack.snapshot()
        repair = self.proposal("disable_persistence", current["persistence"]["target_ref"])
        executed = self.execute(repair)
        self.assertEqual(executed["status"], "executed")
        self.assertFalse(executed["rollback_available"])
        result = self.observation(repair)
        self.assertEqual(result["verdict"], "verified", result)
        self.assertGreaterEqual(result["observation_seconds"], 2.2)
        self.assertEqual(self.stack.call("/actions/" + repair["action_id"] + "/rollback", {}, True)[0], 409)
        _, other_run = self.stack.verify(repair, "different-run")
        self.assertEqual(other_run["evidence"]["data"]["verdict"], "inconclusive")
        _, export = http(self.stack.urls["gateway"] + "/incidents/CG-HOST-001/runs/" + self.run_id,
                         self.stack.tokens["gateway"])
        self.assertEqual(export["audit_status"], "valid")
        self.assertEqual([a["verification"] for a in export["action_states"]], ["failed", "verified"])

    def test_stale_pid_bound_approval_cannot_kill_replacement(self):
        _, before = self.stack.snapshot()
        old = next(p for p in before["processes"] if p["role"] == "compute")
        stale = self.proposal("terminate_process", old["target_ref"])
        first = self.proposal("terminate_process", old["target_ref"])
        self.execute(first)
        time.sleep(1.2)
        _, current = self.stack.snapshot()
        replacement = next(p for p in current["processes"] if p["role"] == "compute")
        result = self.execute(stale)
        self.assertEqual(result["status"], "execution_rejected")
        _, after = self.stack.snapshot()
        self.assertIn(replacement["target_ref"], [p["target_ref"] for p in after["processes"]])

    def test_control_target_and_read_credentials_cannot_mutate(self):
        _, before = self.stack.snapshot()
        control = next(p for p in before["processes"] if p["role"] == "control")
        rejected = self.execute(self.proposal("terminate_process", control["target_ref"]))
        self.assertEqual(rejected["status"], "execution_rejected")
        self.assertEqual(http(self.stack.urls["identity"] + "/operations/forbidden",
                              self.stack.tokens["host_reader"], {})[0], 401)
        self.assertEqual(self.observation(rejected)["verdict"], "inconclusive")

    def test_changed_persistence_requires_new_approval(self):
        _, before = self.stack.snapshot()
        action = self.proposal("disable_persistence", before["persistence"]["target_ref"])
        path = self.stack.directory / "host" / "compute-supervisor.json"
        path.write_text(path.read_text() + "\n")
        self.assertEqual(self.execute(action)["status"], "execution_rejected")
        self.assertTrue(path.exists())

    def test_duplicate_dispatch_reconciles_original_receipt_after_executor_restart(self):
        _, before = self.stack.snapshot()
        action = self.proposal("disable_persistence", before["persistence"]["target_ref"])
        result = self.execute(action)
        self.stack.stop("executor")
        self.stack.start("executor")
        _, repeated = self.stack.call("/actions/" + action["action_id"] + "/execute", {})
        self.assertEqual(result, repeated)
        _, events = self.stack.snapshot()
        self.assertEqual(sum(e["event"] == "supervisor_disabled" for e in events["events"]), 1)

    def test_telemetry_failure_never_becomes_green(self):
        _, before = self.stack.snapshot()
        action = self.proposal("disable_persistence", before["persistence"]["target_ref"])
        self.execute(action)
        self.stack.stop("identity")
        self.assertEqual(self.observation(action)["verdict"], "inconclusive")

    def test_control_failure_is_not_successful_containment(self):
        _, before = self.stack.snapshot()
        action = self.proposal("disable_persistence", before["persistence"]["target_ref"])
        self.execute(action)
        control = next(p for p in before["processes"] if p["role"] == "control")
        os.kill(control["pid"], signal.SIGTERM)
        self.assertEqual(self.observation(action)["verdict"], "inconclusive")

    def test_lost_receipt_reconciles_without_repeating_mutation(self):
        proxy = LostResponseProxy(self.stack)
        self.addCleanup(proxy.close)
        self.stack.stop("executor")
        self.stack.overrides["executor"] = {"CYBERGUARD_HOST_LAB_URL": proxy.url}
        self.stack.start("executor")
        _, before = self.stack.snapshot()
        action = self.proposal("disable_persistence", before["persistence"]["target_ref"])
        self.assertEqual(self.execute(action)["status"], "execution_unknown")
        self.assertEqual(self.observation(action)["verdict"], "inconclusive")
        _, reconciled = self.stack.call("/actions/" + action["action_id"] + "/reconcile", {})
        self.assertEqual(reconciled["status"], "executed")
        self.assertEqual(proxy.posts, 1)
        self.assertEqual(self.observation(action)["verdict"], "verified")

    def test_new_environment_rejects_previously_approved_target(self):
        _, before = self.stack.snapshot()
        action = self.proposal("disable_persistence", before["persistence"]["target_ref"])
        self.stack.stop("identity")
        self.stack.start("identity")
        self.assertEqual(self.execute(action)["status"], "execution_rejected")

    def test_later_run_cannot_launder_previous_action_as_success(self):
        _, before = self.stack.snapshot()
        target = next(p for p in before["processes"] if p["role"] == "compute")
        first = self.proposal("terminate_process", target["target_ref"])
        self.execute(first)
        _, other = self.stack.propose_host("other-run", "disable_persistence", before["persistence"]["target_ref"])
        self.execute(other)
        self.assertEqual(self.observation(first)["verdict"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
