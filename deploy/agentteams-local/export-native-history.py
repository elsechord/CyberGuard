#!/usr/bin/env python3
"""Export selected native QwenPaw history and diagnostic log lines, offline.

Input is a private docker-cp snapshot, never a live model invocation. Original
SQLite/log bytes remain private; exports carry their SHA256 and exact row IDs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

ROLES = ("response-planner", "endpoint-forensics", "recovery-verifier")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    known_secrets = []
    for filename in ("services.env", "agentteams-llm.env", "agentteams-local.env"):
        for line in (Path("/root/.config/cyberguard") / filename).read_text().splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if any(x in key.upper() for x in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and len(value) >= 8:
                known_secrets.append(value)
    index = {"scope": "native_snapshot_not_runtime_attestation", "workers": {}}
    for role in ROLES:
        root = args.private_root / role / ".qwenpaw"
        db = root / "workspaces/default/history.db"
        connection = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        rows = [dict(r) for r in connection.execute("SELECT * FROM conversation_history ORDER BY seq")]
        connection.close()
        body = json.dumps({"source_file": str(db), "source_sha256": hashlib.sha256(db.read_bytes()).hexdigest(),
                           "selection": "SELECT * FROM conversation_history ORDER BY seq", "rows": rows}, ensure_ascii=False, indent=2)
        if any(value in body for value in known_secrets):
            raise SystemExit("Known credential found in history; export stopped before writing " + role)
        target = args.out / (role + "-history.json")
        target.write_text(body + "\n")
        log = root / "qwenpaw.log"
        lines = log.read_text(errors="replace").splitlines() if log.exists() else []
        selected = [{"line": number, "text": line} for number, line in enumerate(lines, 1)
                    if any(word in line for word in ("Generic approval pending", "driver_policy", "denied", "Input validation failed"))]
        diagnostic = json.dumps({"source_file": str(log),
                                 "source_sha256": hashlib.sha256(log.read_bytes()).hexdigest() if log.exists() else None,
                                 "selected_lines": selected}, indent=2)
        if any(value in diagnostic for value in known_secrets):
            raise SystemExit("Known credential found in diagnostic log; export stopped")
        (args.out / (role + "-diagnostic.json")).write_text(diagnostic + "\n")
        index["workers"][role] = {"native_history_rows": len(rows), "source_sha256": hashlib.sha256(db.read_bytes()).hexdigest(),
                                  "export_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    (args.out / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(json.dumps(index))


if __name__ == "__main__":
    main()
