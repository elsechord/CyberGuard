import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cyberguard_investigation.evidence import make_bundle


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load("prepare_investigation", "prepare-investigation-task.py")
validator = load("validate_investigation", "validate-investigation-run.py")


class InvestigationAgentTeamsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def pack(self):
        """Synthetic validation fixture, explicitly NOT proof of live execution."""
        run, task, digest = "run-test", "task-1", "a" * 64
        pack = {"schema": "cyberguard-agentteams-run-evidence/v1", "run_id": run,
                "mode": "multi_agent", "bundle_sha256": digest, "sources": [],
                "workers": [], "tool_calls": [], "skill_events": [],
                "budget": {"max_input_tokens": 100, "max_output_tokens": 50, "max_tool_calls": 10}}
        docs = {"task": {"id": task, "run": run, "bundle": digest, "status": "Completed"},
                "workers": [], "tools": [], "skills": [],
                "usage": {"task": task, "in": 20, "out": 5, "model": "test-fixture"}}

        def ref(source, pointer):
            return {"source": source, "pointer": pointer}

        pack["task"] = {k: ref("task", "/" + v) for k, v in
                        {"task_id": "id", "run_id": "run", "bundle_sha256": "bundle", "status": "status"}.items()}
        for i, (role, skills) in enumerate(validator.ROLES.items()):
            wid = "worker-" + str(i)
            docs["workers"].append({"id": wid, "skills": sorted(skills),
                                     "tools": ["mcp-cyberguard-investigation-readonly", "mcp-cyberguard-investigation-report"]})
            pack["workers"].append({"role": role, **{k: ref("workers", f"/{i}/{v}") for k, v in
                                                   {"worker_id": "id", "skills": "skills", "tools": "tools"}.items()}})
            for name in ["read_investigation_evidence"] + (["submit_investigation_report"] if i == 1 else []):
                idx = len(docs["tools"])
                docs["tools"].append({"worker_id": wid, "task_id": task, "run_id": run,
                                      "bundle_sha256": digest, "call_id": f"call-{idx}", "tool": name})
                pack["tool_calls"].append({k: ref("tools", f"/{idx}/{k}") for k in docs["tools"][-1]})
            for phase in ("loaded", "invoked"):
                idx = len(docs["skills"])
                docs["skills"].append({"worker_id": wid, "task_id": task, "skill": sorted(skills)[0],
                                       "event_id": f"skill-{idx}", "phase": phase})
                pack["skill_events"].append({k: ref("skills", f"/{idx}/{k}") for k in docs["skills"][-1]})
        pack["usage"] = {k: ref("usage", "/" + v) for k, v in
                         {"task_id": "task", "input_tokens": "in", "output_tokens": "out", "model": "model"}.items()}
        kinds = {"task": "native_task", "workers": "native_workers", "tools": "native_tool_events",
                 "skills": "native_skill_events", "usage": "native_model_usage"}
        for sid, doc in docs.items():
            raw = json.dumps(doc).encode()
            (self.root / (sid + ".json")).write_bytes(raw)
            pack["sources"].append({"id": sid, "kind": kinds[sid], "path": sid + ".json",
                                    "sha256": hashlib.sha256(raw).hexdigest()})
        return pack

    def test_prepared_task_is_not_a_live_claim_and_does_not_copy_answers(self):
        path = self.root / "bundle.json"
        path.write_text(json.dumps(make_bundle([], provenance={"kind": "exercise"})))
        (self.root / "ground-truth.json").write_text('"DO_NOT_EXPOSE"')
        result = prepare.prepare(path, self.root / "task", "run-one", "multi_agent", "configured-model", 12000, 4000, 24)
        self.assertEqual(result["status"], "not_run")
        self.assertIsNone(result["usage"])
        self.assertEqual(len(list((self.root / "task").iterdir())), 4)
        self.assertNotIn("DO_NOT_EXPOSE", (self.root / "task" / "task.md").read_text(encoding="utf8"))
        with self.assertRaises(FileExistsError):
            prepare.prepare(path, self.root / "task", "run-one", "multi_agent", "model", 12000, 4000, 24)

    def test_structural_success_is_never_runtime_attestation(self):
        result = validator.validate(self.pack(), self.root)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["status"], "structurally_complete_not_attested")
        self.assertEqual(result["runtime_attestation"], "not_attested")

    def test_self_reported_task_literal_rejected(self):
        pack = self.pack()
        pack["task"]["task_id"] = "task-1"
        self.assertFalse(validator.validate(pack, self.root)["valid"])

    def test_cross_run_or_missing_worker_read_rejected(self):
        pack = self.pack()
        pack["run_id"] = "different-run"
        self.assertFalse(validator.validate(pack, self.root)["valid"])
        pack = self.pack()
        pack["tool_calls"].pop(0)
        self.assertFalse(validator.validate(pack, self.root)["valid"])

    def test_skill_config_without_invocation_rejected(self):
        pack = self.pack()
        pack["skill_events"] = []
        self.assertFalse(validator.validate(pack, self.root)["valid"])

    def test_no_model_usage_or_over_budget_rejected(self):
        pack = self.pack()
        del pack["usage"]
        self.assertFalse(validator.validate(pack, self.root)["valid"])
        pack = self.pack()
        pack["budget"]["max_input_tokens"] = 1
        self.assertFalse(validator.validate(pack, self.root)["valid"])

    def test_tampered_or_escaping_source_rejected(self):
        pack = self.pack()
        (self.root / "task.json").write_text('{}')
        self.assertFalse(validator.validate(pack, self.root)["valid"])
        pack = self.pack()
        pack["sources"][0]["path"] = "../outside.json"
        self.assertFalse(validator.validate(pack, self.root)["valid"])

    def test_not_run_is_explicit_failure(self):
        result = validator.validate({"schema": "cyberguard-agentteams-run-evidence/v1", "status": "not_run"}, self.root)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "not_run")

    def test_mcp_contains_run_and_no_approval_endpoint(self):
        response = (ROOT / "agentteams/mcp/cyberguard-response.yaml").read_text(encoding="utf8")
        self.assertIn("name: run_id", response)
        self.assertIn("target_ref", response)
        for name in ("cyberguard-response", "cyberguard-investigation-readonly", "cyberguard-investigation-report"):
            text = (ROOT / f"agentteams/mcp/{name}.yaml").read_text(encoding="utf8")
            self.assertNotIn("/actions/approve", text)
            self.assertNotIn("APPROVAL_SECRET", text)


if __name__ == "__main__":
    unittest.main()
