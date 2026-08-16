import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bootstrap = load("bootstrap_agentteams", ROOT / "deploy" / "bootstrap-agentteams.py")
validator = load("validate_agentteams_state", ROOT / "deploy" / "validate-agentteams-state.py")


class FakeMatrix:
    def call(self, method, path, payload=None):
        if path.endswith("joined_rooms"):
            return {"joined_rooms": ["!manager:local", "!team:local"]}
        if "%21manager%3Alocal" in path:
            return {"chunk": [
                {"state_key": "@admin:local", "content": {"membership": "join"}},
                {"state_key": "@manager:local", "content": {"membership": "join"}},
            ]}
        return {"chunk": [
            {"state_key": "@admin:local", "content": {"membership": "join"}},
            {"state_key": "@alice:local", "content": {"membership": "join"}},
            {"state_key": "@bob:local", "content": {"membership": "join"}},
            {"state_key": "@manager-team:local", "content": {"membership": "join"}},
        ]}


class AgentTeamsBootstrapTest(unittest.TestCase):
    def manifest(self):
        return {
            "schema_version": 1, "status": "complete",
            "team": {"name": "cyberguard-soc", "room_id": "!cyberguard:local"},
            "tool_services": ["cyberguard-readonly", "cyberguard-response"],
            "approval_secret_exposed": False,
            "workers": [
                {"name": name, "ready": True, "skills": sorted(skills), "tools": sorted(tools)}
                for name, (skills, tools) in validator.EXPECTED.items()
            ],
        }

    def workers_snapshot(self, *, tool_override=None, omit_skill_for=None):
        """A live ``agt get workers -o json``-style CR snapshot.

        The manifest is intentionally not used to populate this fixture: the
        validator must prove bindings from the Worker CRs themselves.
        """
        items = []
        for name, (skills, tools) in validator.EXPECTED.items():
            live_skills = sorted(skills)
            if name == omit_skill_for:
                live_skills.pop()
            live_tools = sorted(tools if tool_override is None or name not in tool_override
                                else tool_override[name])
            items.append({
                "metadata": {"name": name},
                "spec": {
                    "skills": [*live_skills, "communication", "task-management"],
                    # Exercise the actual AgentTeams ``mcp-`` client spelling.
                    "mcpClients": [f"mcp-{tool}" for tool in live_tools],
                },
                # A status value must not count as a live binding.
                "status": {"message": "MCP clients were configured"},
            })
        return {"items": items}

    def test_request_is_stable_and_contains_no_secret_values(self):
        message, digest, bundle_digest = bootstrap.build_request(ROOT / "agentteams" / "bootstrap-manager-request.md")
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertIsNone(bundle_digest)
        self.assertIn(digest, message)
        self.assertNotIn("CYBERGUARD_APPROVAL_SECRET=", message)
        self.assertNotIn("CYBERGUARD_AUDIT_HMAC_KEY=", message)
        self.assertIn("ten ZIP packages", message)
        self.assertIn("boundary-defense", validator.EXPECTED["network-hunter"][0])

    def test_request_binds_bootstrap_bundle_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "BOOTSTRAP-SHA256SUMS"
            manifest.write_text("abc  skills/example.zip\n", encoding="utf-8")
            message, _, digest = bootstrap.build_request(
                ROOT / "agentteams" / "bootstrap-manager-request.md", manifest
            )
            self.assertRegex(digest or "", r"^[0-9a-f]{64}$")
            self.assertIn(f"CYBERGUARD_BOOTSTRAP_BUNDLE_SHA256={digest}", message)

    def test_finds_exact_manager_dm_not_team_room(self):
        self.assertEqual(bootstrap.find_manager_room(FakeMatrix(), "@admin:local"),
                         ("!manager:local", "@manager:local"))

    def test_accepts_exact_worker_skill_and_tool_state_with_cr_snapshots(self):
        workers = self.workers_snapshot()
        teams = {"items": [{"metadata": {"name": "cyberguard-soc"}}]}
        result = validator.validate(self.manifest(), workers, teams)
        self.assertTrue(result["valid"], result["issues"])
        self.assertTrue(result["cr_snapshots_checked"])
        self.assertTrue(result["live_worker_bindings_checked"])
        self.assertEqual(
            result["observed_worker_bindings"]["alert-fusion"]["tools"],
            ["cyberguard-readonly"],
        )

    def test_rejects_manager_claim_when_live_worker_has_no_mcp_binding(self):
        workers = self.workers_snapshot(tool_override={"threat-intel": set()})
        teams = {"items": [{"metadata": {"name": "cyberguard-soc"}}]}
        result = validator.validate(self.manifest(), workers, teams)
        self.assertFalse(result["valid"])
        self.assertTrue(any(
            "threat-intel live Worker CR tool boundary" in issue for issue in result["issues"]
        ))

    def test_rejects_live_worker_skill_drift_even_when_manifest_claims_success(self):
        workers = self.workers_snapshot(omit_skill_for="network-hunter")
        teams = {"items": [{"metadata": {"name": "cyberguard-soc"}}]}
        result = validator.validate(self.manifest(), workers, teams)
        self.assertFalse(result["valid"])
        self.assertTrue(any(
            "network-hunter live Worker CR skill" in issue for issue in result["issues"]
        ))

    def test_rejects_privilege_drift_and_missing_worker_cr(self):
        manifest = self.manifest()
        next(item for item in manifest["workers"] if item["name"] == "alert-fusion")["tools"].append("cyberguard-response")
        workers = self.workers_snapshot()
        workers["items"] = [item for item in workers["items"]
                            if item["metadata"]["name"] != "threat-intel"]
        teams = {"items": [{"metadata": {"name": "cyberguard-soc"}}]}
        result = validator.validate(manifest, workers, teams)
        self.assertFalse(result["valid"])
        self.assertTrue(any("tool boundary" in issue for issue in result["issues"]))
        self.assertTrue(any("threat-intel" in issue for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
