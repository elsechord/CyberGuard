#!/usr/bin/env python3
"""Generate local-only service secrets without printing them or inventing an LLM key."""
import os
import argparse
from pathlib import Path
import secrets


def main():
    if os.name != "posix":
        raise SystemExit("Run in WSL/Linux so service secrets can be created with mode 0600.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path.home()/'.config/cyberguard')
    args = parser.parse_args()
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "agentteams-local.env"
    values = {"AGENTTEAMS_ADMIN_USER": "admin", "AGENTTEAMS_MINIO_USER": "admin",
              "AGENTTEAMS_LLM_PROVIDER": "openai-compat",
              "AGENTTEAMS_LLM_API_KEY": "", "AGENTTEAMS_DEFAULT_MODEL": "",
              "AGENTTEAMS_OPENAI_BASE_URL": "http://127.0.0.1:1/v1"}
    for name in ("ADMIN_PASSWORD", "MANAGER_PASSWORD", "REGISTRATION_TOKEN", "MINIO_PASSWORD",
                 "MANAGER_GATEWAY_KEY", "MATRIX_APPSERVICE_AS_TOKEN", "MATRIX_APPSERVICE_HS_TOKEN"):
        values["AGENTTEAMS_" + name] = secrets.token_hex(32)
    # O_EXCL preserves existing secrets, making reruns safe.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Local configuration already exists; preserved. Model configuration not changed.")
        return
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Local service credentials; never commit or paste into agent prompts.\n")
        stream.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print("Created ignored local configuration. LLM key absent; Manager disabled; model tasks pending.")


if __name__ == "__main__":
    main()
