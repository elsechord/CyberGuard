import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CiContractTests(unittest.TestCase):
    def test_all_remote_actions_are_full_sha_pinned(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)", workflow, re.MULTILINE)
        self.assertGreaterEqual(len(uses), 8)
        for reference in uses:
            self.assertRegex(reference, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}$")

    def test_workflow_is_least_privilege_and_avoids_dangerous_trigger(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertRegex(workflow, r"permissions:\s*\n\s*contents: read")
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotRegex(workflow, r"permissions:\s*write-all")

    def test_ci_scans_source_and_both_images_and_emits_three_sboms(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("scan-type: fs", workflow)
        self.assertEqual(workflow.count("image-ref: cyberguard/"), 2)
        self.assertIn("gateway.spdx.json", workflow)
        self.assertIn("executor.spdx.json", workflow)
        self.assertIn("source.spdx.json", workflow)

    def test_dependabot_covers_actions_python_and_docker(self):
        config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        self.assertEqual(config.count("package-ecosystem: pip"), 2)
        self.assertEqual(config.count("package-ecosystem: docker"), 2)
        self.assertEqual(config.count("package-ecosystem: github-actions"), 1)

    def test_container_and_ci_installs_require_hash_locked_dependencies(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("--require-hashes -r services/requirements.lock", workflow)
        lock = (ROOT / "services" / "requirements.lock").read_text(encoding="utf-8")
        self.assertGreaterEqual(lock.count("--hash=sha256:"), 14)
        for dockerfile in (ROOT / "services").glob("*/Dockerfile"):
            content = dockerfile.read_text(encoding="utf-8")
            self.assertIn("--require-hashes", content)
            self.assertIn("pip check", content)

    def test_ci_generates_ephemeral_compose_secrets_and_removes_them(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("python deploy/init_secrets.py", workflow)
        self.assertIn("rm -f .env", workflow)
        self.assertNotRegex(workflow, r"ci-(?:api-token|executor-token|approval-secret)-")


if __name__ == "__main__":
    unittest.main()
