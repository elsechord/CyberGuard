import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validate_config", ROOT / "deploy" / "validate_config.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class DeployConfigTests(unittest.TestCase):
    def cyberguard_values(self) -> dict[str, str]:
        return {
            "CYBERGUARD_API_TOKEN": "a" * 48,
            "CYBERGUARD_EXECUTOR_TOKEN": "b" * 48,
            "CYBERGUARD_APPROVAL_SECRET": "c" * 48,
            "CYBERGUARD_AUDIT_HMAC_KEY": "d" * 48,
            "CYBERGUARD_AUDIT_READER_TOKEN": "e" * 48,
            "CYBERGUARD_ALLOW_INSECURE_HTTP": "0",
            "CYBERGUARD_MIN_EVIDENCE_QUALITY": "0.7",
            "CYBERGUARD_SIEM_BASE_URL": "https://siem.example.invalid/api",
        }

    def agentteams_values(self) -> dict[str, str]:
        return {
            **MODULE.PINNED_AGENTTEAMS,
            "AGENTTEAMS_LLM_API_KEY": "sk-test-only",
            "AGENTTEAMS_DEFAULT_MODEL": "test-model",
            "AGENTTEAMS_ADMIN_PASSWORD": "strong-test-password",
            "AGENTTEAMS_LOCAL_ONLY": "1",
            "AGENTTEAMS_MATRIX_E2EE": "0",
            "AGENTTEAMS_WORKSPACE_DIR": "/srv/cyberguard/agentteams-manager",
            "AGENTTEAMS_HOST_SHARE_DIR": "/srv/cyberguard/host-share",
        }

    def test_valid_profiles(self):
        self.assertEqual(MODULE.validate_cyberguard(self.cyberguard_values())["secret_count"], 5)
        result = MODULE.validate_agentteams(self.agentteams_values(), Path("/srv/cyberguard"))
        self.assertEqual(result["version"], "v1.2.2")

    def test_rejects_duplicate_or_short_cyberguard_secrets(self):
        values = self.cyberguard_values()
        values["CYBERGUARD_EXECUTOR_TOKEN"] = values["CYBERGUARD_API_TOKEN"]
        with self.assertRaisesRegex(MODULE.ConfigError, "distinct"):
            MODULE.validate_cyberguard(values)
        values = self.cyberguard_values()
        values["CYBERGUARD_API_TOKEN"] = "short"
        with self.assertRaisesRegex(MODULE.ConfigError, "at least 32"):
            MODULE.validate_cyberguard(values)

    def test_rejects_insecure_or_credentialed_urls(self):
        values = self.cyberguard_values()
        values["CYBERGUARD_SIEM_BASE_URL"] = "http://siem.example.invalid"
        with self.assertRaisesRegex(MODULE.ConfigError, "HTTPS"):
            MODULE.validate_cyberguard(values)
        values["CYBERGUARD_ALLOW_INSECURE_HTTP"] = "1"
        values["CYBERGUARD_SIEM_BASE_URL"] = "http://user:password@siem.example.invalid"
        with self.assertRaisesRegex(MODULE.ConfigError, "credential-free"):
            MODULE.validate_cyberguard(values)

    def test_rejects_invalid_evidence_quality_threshold(self):
        values = self.cyberguard_values()
        values["CYBERGUARD_MIN_EVIDENCE_QUALITY"] = "1.1"
        with self.assertRaisesRegex(MODULE.ConfigError, "number from 0 to 1"):
            MODULE.validate_cyberguard(values)

    def test_rejects_agentteams_pin_and_path_drift(self):
        values = self.agentteams_values()
        values["AGENTTEAMS_VERSION"] = "latest"
        with self.assertRaisesRegex(MODULE.ConfigError, "validated AgentTeams"):
            MODULE.validate_agentteams(values, Path("/srv/cyberguard"))
        values = self.agentteams_values()
        values["AGENTTEAMS_WORKSPACE_DIR"] = "/tmp/manager"
        with self.assertRaisesRegex(MODULE.ConfigError, "WORKSPACE_DIR"):
            MODULE.validate_agentteams(values, Path("/srv/cyberguard"))

    def test_parser_rejects_duplicate_keys_without_leaking_values(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.env"
            path.write_text("TOKEN=first-secret\nTOKEN=second-secret\n", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ConfigError, "duplicate variable TOKEN") as caught:
                MODULE.parse_env(path)
            self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
