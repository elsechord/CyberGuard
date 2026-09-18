"""Create one private, immutable local model-boundary configuration in WSL/Linux."""
import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cyberguard_investigation.evidence import load_bundle
from cyberguard_investigation.model_runner import read_secret_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--name-prefix", required=True)
    parser.add_argument("--model-env", type=Path, required=True)
    parser.add_argument("--directory", type=Path, default=Path.home() / ".config/cyberguard")
    args = parser.parse_args()
    if os.name != "posix" or stat.S_IMODE(args.model_env.stat().st_mode) & 0o077:
        raise SystemExit("Use a private POSIX model env file")
    bundle = load_bundle(args.bundle)
    if bundle["provenance"]["kind"] != "exercise":
        raise SystemExit("Only exercise evidence is authorized for this integration")
    env = read_secret_file(args.model_env)
    config = {"run_id": args.run_id, "model": env["AGENTTEAMS_DEFAULT_MODEL"],
        "evidence_hash": bundle["bundle_sha256"],
        "upstream_endpoint": env["AGENTTEAMS_OPENAI_BASE_URL"].rstrip("/") + "/chat/completions",
        "upstream_key": env["AGENTTEAMS_LLM_API_KEY"], "admin_token": secrets.token_urlsafe(48),
        "roles": {role: {"token": secrets.token_urlsafe(48), "model_alias": args.name_prefix + "-" + role + "-model",
                    # memory_search is injected by the QwenPaw Matrix task channel itself
                    # (2026-09-18 disarmed probe, declaration-investigator.json): it is not
                    # part of builtin_tools and cannot be disabled through the native
                    # runtime policy. It only searches the Worker's own local memory store
                    # (fresh identities start empty), so admitting it is the minimal
                    # channel-level addition; every other tool stays default-deny.
                    "allowed_tools": ["Skill", "memory_search",
                        "mcp-cyberguard-investigation-readonly__read_investigation_evidence",
                        "mcp-cyberguard-investigation-readonly__read_investigation_reports",
                        "mcp-cyberguard-investigation-report__submit_investigation_report"]}
                  for role in ("investigator", "planner", "verifier")},
        "limits": {"max_requests": 9, "max_requests_per_role": 3, "max_input_tokens": 300000,
                   "max_output_tokens": 24000, "max_concurrency": 1},
        "max_output_per_request": 6000, "input_overhead_reservation": 2048, "upstream_timeout_seconds": 90}
    args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path, env_path = (args.directory / name for name in ("model-guard-config.json", "model-guard.env"))
    if config_path.exists() or env_path.exists():
        raise SystemExit("Configuration already exists; refusing to rotate or reset an existing run")
    # Docker Compose's raw env-file format preserves JSON punctuation and dollar signs.
    for path, content in ((config_path, json.dumps(config, indent=2) + "\n"),
                          (env_path, "CYBERGUARD_MODEL_GUARD_CONFIG=" + json.dumps(config, separators=(",", ":")) + "\n")):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
    print(json.dumps({"run_id": args.run_id, "config_path": str(config_path), "roles": list(config["roles"]),
                      "limits": config["limits"], "armed": False}))


if __name__ == "__main__":
    main()
