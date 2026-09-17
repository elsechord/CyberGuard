"""Process-lab integration harness. Credentials never belong to agent packages."""
import secrets
import sys
from uuid import uuid4

from lab_support import LabStack, ROOT, http


class HostLabStack(LabStack):
    def __init__(self, directory=None):
        super().__init__(directory)
        self.tokens["host_reader"] = secrets.token_urlsafe(36)

    def command(self, role):
        if role == "identity":
            return [sys.executable, str(ROOT / "services/host-lab/server.py"),
                    "--directory", str(self.directory / "host"), "--port", str(self.ports[role])]
        return super().command(role)

    def environment(self, role):
        env = super().environment(role)
        for key in list(env):
            if key.startswith("CYBERGUARD_LAB_"):
                del env[key]
        if role == "identity":
            env.update(CYBERGUARD_HOST_ADMIN_TOKEN=self.tokens["admin"],
                       CYBERGUARD_HOST_READER_TOKEN=self.tokens["host_reader"])
        elif role == "executor":
            env.update(CYBERGUARD_HOST_LAB_URL=self.urls["identity"],
                       CYBERGUARD_EXECUTION_MODE="host_lab", CYBERGUARD_HOST_ADMIN_TOKEN=self.tokens["admin"])
        else:
            env.update(CYBERGUARD_HOST_LAB_URL=self.urls["identity"],
                       CYBERGUARD_HOST_READER_TOKEN=self.tokens["host_reader"])
        env.update(self.overrides.get(role, {}))
        return env

    def collect(self, run_id):
        return http(self.urls["gateway"] + "/tools/endpoint/timeline", self.tokens["gateway"], {
            "incident_id": "CG-HOST-001", "scenario_id": "lab_host", "run_id": run_id})

    def propose_host(self, run_id, action, target, key=None):
        return self.call("/actions/propose", {"incident_id": "CG-HOST-001", "run_id": run_id,
            "model_mode": "deterministic", "action": action, "target": target,
            "reason": "Review the observed laboratory target and independently verify the outcome.",
            "idempotency_key": key or uuid4().hex})

    def verify(self, action, run_id=None):
        return http(self.urls["gateway"] + "/tools/recovery/metrics", self.tokens["gateway"], {
            "incident_id": action["incident_id"], "scenario_id": "lab_host", "run_id": run_id or action["run_id"],
            "arguments": {"action_id": action["action_id"]}})

    def approve(self, action, approver="automated-lab-harness"):
        return self.call("/actions/approve", {"action_id": action["action_id"], "approver": approver}, True)

    def snapshot(self):
        return http(self.urls["identity"] + "/snapshot?nonce=" + uuid4().hex, self.tokens["host_reader"])
