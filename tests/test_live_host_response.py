"""The planner cannot select an unobserved target or widen initial operator scope."""
import importlib.util
import io
import json
import unittest
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("live_host_response", Path(__file__).resolve().parents[1] / "scripts/live-host-response.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PlannerBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.observation = {"evidence": {"data": {"processes": [
            {"role": "compute", "target_ref": "process:fresh"},
            {"role": "control", "target_ref": "process:business"}],
            "persistence": {"present": True, "target_ref": "persistence:fresh"}}}}
        self.config = {"model": "test-model", "upstream_endpoint": "https://example.invalid/v1/chat/completions", "upstream_key": "unit-test-placeholder"}

    def call(self, action, target, previous=None):
        response = {"choices": [{"message": {"content": json.dumps({"action": action, "target": target, "reason": "Fresh evidence supports this scoped response."})}}], "usage": {"total_tokens": 10}}
        with patch.object(module, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(response).encode())
            result = module.plan(self.config, self.observation, previous, "digest", {"summary": "Prior case"})
            sent = json.loads(opener.return_value.open.call_args.args[0].data)
            self.assertIn("Prior case", sent["messages"][1]["content"])
            self.assertNotIn("unit-test-placeholder", sent["messages"][1]["content"])
            return result

    def test_fresh_target_and_context_are_accepted(self):
        self.assertEqual(self.call("terminate_process", "process:fresh")[0]["target"], "process:fresh")

    def test_business_workload_and_stale_target_rejected(self):
        for target in ("process:business", "process:stale"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.call("terminate_process", target)

    def test_initial_scope_requires_process_only_and_repair_can_expand(self):
        with self.assertRaises(ValueError):
            self.call("disable_persistence", "persistence:fresh")
        self.assertEqual(self.call("disable_persistence", "persistence:fresh", {"verdict": "failed"})[0]["action"], "disable_persistence")

    def test_native_report_uses_live_evidence_and_exports_job(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = root / "private-key"
            key.write_text("test-placeholder", encoding="utf-8")
            args = SimpleNamespace(skill_key_file=key, native_console_url="http://127.0.0.1:1", native_deadline=1)
            responses = [{"data": {"id": "INV-test"}}, {"data": {"id": "INV-test", "status": "completed",
                "report": {"summary": "Observed compute recurrence", "findings": []}}}]
            with patch.object(module, "build_opener") as opener:
                opener.return_value.open.side_effect = [io.BytesIO(json.dumps(r).encode()) for r in responses]
                report, digest, job = module.native_investigate(args, root, "RUN-test", 2, self.observation, {"verdict": "failed"})
            self.assertEqual(job, "INV-test")
            self.assertEqual(len(digest), 64)
            sent = json.loads((root / "round-2-native-request.json").read_text(encoding="utf-8"))
            self.assertIn("process:fresh", sent["materials"][0]["content"])
            self.assertIn("failed", sent["materials"][1]["content"])
            self.assertNotIn("test-placeholder", (root / "round-2-native-request.json").read_text(encoding="utf-8"))
            self.assertTrue((root / "round-2-native-job.json").exists())


if __name__ == "__main__":
    unittest.main()
