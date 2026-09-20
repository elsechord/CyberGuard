"""Prepare a fresh bounded console validation; preserve all previous runs/secrets."""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RUN = "CG-CONSOLE-20260920-001"
PREFIX = "cg-console001"
PRIVATE = Path("/root/.config/cyberguard/console-validation-001")
PLAN = ROOT.parent / "output/console-agentteams-validation-001"


def main():
    if PRIVATE.exists() or PLAN.exists():
        raise SystemExit("Fresh validation paths already exist; refusing reset")
    original = dict(line.split("=", 1) for line in Path("/root/.config/cyberguard/agentteams-llm.env").read_text().splitlines()
                    if line and not line.startswith("#") and "=" in line)
    spec = importlib.util.spec_from_file_location("prepare", ROOT / "deploy/agentteams-local/prepare-guarded-team.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.prepare(PLAN, RUN, PREFIX, original["AGENTTEAMS_DEFAULT_MODEL"],
                   "http://console-model-guard.agentteams.local:8080/v1")
    config = {"run_id": RUN, "model": original["AGENTTEAMS_DEFAULT_MODEL"],
              "evidence_hash": __import__("hashlib").sha256(b"console synthetic login validation").hexdigest(),
              "upstream_endpoint": original["AGENTTEAMS_OPENAI_BASE_URL"].rstrip("/") + "/chat/completions",
              "upstream_key": original["AGENTTEAMS_LLM_API_KEY"], "admin_token": secrets.token_urlsafe(48),
              "roles": {r: {"token": secrets.token_urlsafe(48), "model_alias": PREFIX + "-" + r + "-model",
                            "allowed_tools": ["Skill", "memory_search"]} for r in ("investigator", "planner", "verifier")},
              "limits": {"max_requests": 9, "max_requests_per_role": 3, "max_input_tokens": 150000,
                         "max_output_tokens": 12000, "max_concurrency": 1},
              "max_output_per_request": 2000, "input_overhead_reservation": 2048, "upstream_timeout_seconds": 90}
    PRIVATE.mkdir(mode=0o700)
    for name, value in (("model-guard-config.json", json.dumps(config)),
                        ("model-guard.env", "CYBERGUARD_MODEL_GUARD_CONFIG=" + json.dumps(config, separators=(",", ":")) + "\n")):
        fd = os.open(PRIVATE / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(value)
    subprocess.run(["docker", "run", "-d", "--name", "cyberguard-console-model-guard", "--network", "agentteams-net",
                    "--network-alias", "console-model-guard.agentteams.local", "--env-file", str(PRIVATE / "model-guard.env"),
                    "-e", "CYBERGUARD_DATA_DIR=/data", "-v", "cyberguard-console-guard-001:/data",
                    "-p", "127.0.0.1:18111:8080", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                    "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "cyberguard/model-guard:local"], check=True)
    print(json.dumps({"run_id": RUN, "plan": str(PLAN), "private_directory": str(PRIVATE), "armed": False}))


if __name__ == "__main__":
    main()
