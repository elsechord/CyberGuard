import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeployContractTests(unittest.TestCase):
    def test_compose_keeps_host_ports_loopback_and_containers_hardened(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        published = re.findall(r'"([^\"]+:[0-9]+:[0-9]+)"', compose)
        self.assertGreaterEqual(len(published), 2)
        self.assertTrue(all(value.startswith("127.0.0.1:") for value in published))
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertRegex(compose, r"cap_drop:\s*\n\s*- ALL")
        self.assertRegex(compose, r"agentteams-net:\s*\n\s*external: true")

    def test_bootstrap_orders_preflight_config_install_and_acceptance(self):
        script = (ROOT / "deploy" / "bootstrap-server.sh").read_text(encoding="utf-8")
        markers = [
            "bash deploy/preflight.sh host",
            "python3 deploy/validate_config.py",
            "bash deploy/install-agentteams.sh",
            "bash deploy/preflight.sh cyberguard",
            "bash deploy/server-acceptance.sh",
        ]
        offsets = [script.index(marker) for marker in markers]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("grep -qx 'agentteams-controller'", script)
        self.assertNotIn("if ! docker network inspect agentteams-net", script)

    def test_acceptance_validates_before_mutating_docker_state(self):
        script = (ROOT / "deploy" / "server-acceptance.sh").read_text(encoding="utf-8")
        self.assertLess(script.index("validate_config.py"), script.index("docker compose build"))
        self.assertIn("EVIDENCE_DIR=\"$RUN_DIR/e2e\"", script)
        self.assertIn("sha256sum \"$ARCHIVE\"", script)

    def test_acceptance_captures_failure_and_provenance_evidence(self):
        script = (ROOT / "deploy" / "server-acceptance.sh").read_text(encoding="utf-8")
        self.assertIn("trap collect_failure_evidence ERR", script)
        self.assertIn("failure-compose-ps.json", script)
        self.assertIn("image-identities.jsonl", script)
        self.assertIn("acceptance-manifest.json", script)
        self.assertLess(script.index("agentteams-version.txt"), script.index("find . -type f"))
        self.assertIn('! -name \'acceptance.log\'', script)

    def test_public_release_excludes_runtime_evidence(self):
        script = (ROOT / "scripts" / "package-release.ps1").read_text(encoding="utf-8")
        for restricted in ("benchmark/results", "benchmark/room-map.json", "artifacts"):
            self.assertIn(f"--exclude='{restricted}'", script)
            self.assertIn(f'"{restricted}', script)

    def test_preflight_rejects_non_x86_64_hosts_for_current_lock(self):
        script = (ROOT / "deploy" / "preflight.sh").read_text(encoding="utf-8")
        self.assertIn('architecture="$(uname -m)"', script)
        self.assertIn('"$architecture" != "x86_64"', script)
        self.assertIn("hash-locked Python wheel set", script)

    def test_judge_demo_runs_both_scenarios_and_emits_verifiable_summary(self):
        script = (ROOT / "deploy" / "judge-demo.sh").read_text(encoding="utf-8")
        self.assertIn("credential_compromise supply_chain_webshell", script)
        self.assertIn("demo-summary.json", script)
        self.assertIn("SHA256SUMS", script)
        e2e = (ROOT / "tests" / "e2e_demo.sh").read_text(encoding="utf-8")
        self.assertIn('SCENARIO_ID="${1:-credential_compromise}"', e2e)
        self.assertIn("compromised_token_disabled", e2e)
        self.assertIn("boundary/policy", e2e)
        self.assertIn("required_action_contract_enforced", e2e)
        self.assertIn('ACTIONS=("disable_account|finance-ops"', e2e)

    def test_audit_hmac_key_is_executor_only_and_acceptance_exports_checkpoint(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        gateway, executor = compose.split("  response-executor:", 1)
        self.assertNotIn("CYBERGUARD_AUDIT_HMAC_KEY", gateway)
        self.assertIn("CYBERGUARD_AUDIT_HMAC_KEY", executor)
        self.assertIn("CYBERGUARD_AUDIT_READER_TOKEN", gateway)
        self.assertIn("CYBERGUARD_AUDIT_READER_TOKEN", executor)
        self.assertIn("CYBERGUARD_AUDIT_VERIFY_URL", gateway)
        acceptance = (ROOT / "deploy" / "server-acceptance.sh").read_text(encoding="utf-8")
        self.assertIn("audit-checkpoint.json", acceptance)

    def test_server_bootstrap_prepares_agentteams_assets_and_readiness_cross_checks_crs(self):
        bootstrap = (ROOT / "deploy" / "bootstrap-server.sh").read_text(encoding="utf-8")
        self.assertIn("bash deploy/prepare-agentteams-bootstrap.sh", bootstrap)
        readiness = (ROOT / "deploy" / "competition-readiness.sh").read_text(encoding="utf-8")
        self.assertIn("agt get workers -o json", readiness)
        self.assertIn("agt get teams -o json", readiness)
        self.assertIn("validate-agentteams-state.py", readiness)
        self.assertIn("audit-checkpoint.json", readiness)

    def test_ten_skill_catalog_includes_boundary_defense_and_matches_manager_request(self):
        skills = sorted(
            path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")
        )
        self.assertEqual(len(skills), 10)
        self.assertIn("boundary-defense", skills)
        request = (ROOT / "agentteams" / "bootstrap-manager-request.md").read_text(encoding="utf-8")
        self.assertIn("ten ZIP packages", request)
        connectors = json.loads((ROOT / "config" / "connectors.json.example").read_text(encoding="utf-8"))
        boundary = connectors["connectors"]["boundary.policy"]
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in (boundary["base_url_env"], boundary["token_env"]):
            self.assertIn(key, compose)
            self.assertIn(key, env_example)

    def test_agentteams_workers_have_a_simplified_chinese_language_policy(self):
        request = (ROOT / "agentteams" / "create-team-message.md").read_text(encoding="utf-8")
        bootstrap = (ROOT / "agentteams" / "bootstrap-manager-request.md").read_text(encoding="utf-8")
        self.assertIn("Simplified Chinese", request)
        self.assertIn("Simplified-Chinese language policy", bootstrap)


if __name__ == "__main__":
    unittest.main()
