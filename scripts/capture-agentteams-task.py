#!/usr/bin/env python3
"""Capture one real CyberGuard AgentTeams task end-to-end as a judge evidence pack.

Sends the WebShell demo task to the cyberguard-soc Team room over native Matrix,
records the complete room event chain, polls the CyberGuard services for incident /
audit state, and detects L2 actions awaiting human approval. Approvals themselves
are performed by a human operator with scripts/approve-action.sh so the evidence
shows a genuine human gate.

There is deliberately no early-exit heuristic: intermediate coordination chatter
also mentions reports. Capture runs until --timeout; the operator stops it once
the Team Leader's final report has actually been published. Use --skip-send when
resuming capture for a task that was already sent.

Usage (on the server, repo at /srv/cyberguard):
    python3 scripts/capture-agentteams-task.py \
        --env-file /srv/cyberguard/agentteams.env \
        --cyberguard-env /srv/cyberguard/.env \
        --task-file /srv/cyberguard/agentteams/demo-task-supply-chain.md \
        --out /srv/cyberguard/artifacts/live-task/webshell-<ts>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

ACTION_ID = re.compile(r"ACT-[0-9a-f]{12}")
APPROVAL_HINT = re.compile(r"审批|批准|approve|approval", re.IGNORECASE)


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


@dataclass
class MatrixClient:
    base_url: str
    access_token: str

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Matrix {method} {path} failed: HTTP {exc.code}: {detail}") from exc

    def sync(self, since: str | None = None, timeout_ms: int = 0) -> dict[str, Any]:
        query = {"timeout": str(timeout_ms)}
        if since:
            query["since"] = since
        return self._json("GET", "/_matrix/client/v3/sync?" + parse.urlencode(query))

    def send_text(self, room_id: str, body: str) -> str:
        txn = uuid.uuid4().hex
        room = parse.quote(room_id, safe="")
        result = self._json(
            "PUT",
            f"/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}",
            {"msgtype": "m.text", "body": body},
        )
        return str(result["event_id"])

    def joined_rooms(self) -> list[str]:
        return list(self._json("GET", "/_matrix/client/v3/joined_rooms").get("joined_rooms", []))

    def room_state_name(self, room_id: str) -> str:
        room = parse.quote(room_id, safe="")
        try:
            event = self._json("GET", f"/_matrix/client/v3/rooms/{room}/state/m.room.name/")
            return str(event.get("name", ""))
        except Exception:
            return ""


def login(base_url: str, username: str, password: str) -> str:
    payload = json.dumps(
        {
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": username},
            "password": password,
        }
    ).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + "/_matrix/client/v3/login",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=45) as response:
        return str(json.loads(response.read().decode("utf-8"))["access_token"])


def http_get(url: str, token: str) -> Any:
    req = request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True, help="agentteams.env")
    parser.add_argument("--cyberguard-env", type=Path, required=True, help="CyberGuard .env")
    parser.add_argument("--task-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--room-name", default="cyberguard-soc")
    parser.add_argument("--matrix-base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--gateway", default="http://127.0.0.1:18100")
    parser.add_argument("--executor", default="http://127.0.0.1:18105")
    parser.add_argument("--incident-id", default="CG-2026-0002")
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--skip-send", action="store_true", help="do not send the task again; only capture")
    args = parser.parse_args()

    env = parse_env(args.env_file)
    cg_env = parse_env(args.cyberguard_env)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    token = login(
        args.matrix_base_url,
        env.get("AGENTTEAMS_ADMIN_USER", "admin"),
        env["AGENTTEAMS_ADMIN_PASSWORD"],
    )
    client = MatrixClient(args.matrix_base_url, token)

    room_id = None
    for rid in client.joined_rooms():
        if args.room_name in client.room_state_name(rid):
            room_id = rid
            break
    if not room_id:
        raise SystemExit(f"room containing '{args.room_name}' not found among joined rooms")

    meta = {
        "schema_version": 1,
        "capture_started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "room_id": room_id,
        "incident_id": args.incident_id,
        "task_file": str(args.task_file),
        "task_sha256": hashlib.sha256(args.task_file.read_bytes()).hexdigest(),
    }
    (out / "capture-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")

    initial = client.sync(timeout_ms=0)
    since = str(initial["next_batch"])

    if args.skip_send:
        print("[capture] --skip-send: not re-sending the task, capturing from now on")
    else:
        task_text = args.task_file.read_text(encoding="utf-8")
        request_event_id = client.send_text(room_id, task_text)
        (out / "request-event.json").write_text(
            json.dumps({"event_id": request_event_id, "room_id": room_id}, indent=2) + "\n"
        )
        print(f"[capture] task sent, request_event_id={request_event_id}")

    events_path = out / "matrix-events.jsonl"
    approved_or_pending: set[str] = set()
    started = time.monotonic()
    last_snapshot = 0.0

    with events_path.open("a", encoding="utf-8") as sink:
        while time.monotonic() - started < args.timeout:
            update = client.sync(since=since, timeout_ms=30_000)
            since = str(update["next_batch"])
            room_events = (
                update.get("rooms", {}).get("join", {}).get(room_id, {}).get("timeline", {}).get("events", [])
            )
            for event in room_events:
                sink.write(json.dumps(event, ensure_ascii=False) + "\n")
                sink.flush()
                if event.get("type") != "m.room.message":
                    continue
                body = str(event.get("content", {}).get("body", ""))
                if APPROVAL_HINT.search(body):
                    for action_id in ACTION_ID.findall(body):
                        if action_id not in approved_or_pending:
                            approved_or_pending.add(action_id)
                            print(f"[capture] PENDING APPROVAL: {action_id} — approve with scripts/approve-action.sh {action_id} <approver>")
                            (out / "pending-approvals.json").write_text(
                                json.dumps(sorted(approved_or_pending), indent=2) + "\n"
                            )

            now = time.monotonic()
            if now - last_snapshot >= 30:
                last_snapshot = now
                snap: dict[str, Any] = {"t": round(now - started, 1)}
                try:
                    snap["incident"] = http_get(
                        f"{args.gateway}/incidents/{args.incident_id}", cg_env["CYBERGUARD_API_TOKEN"]
                    )
                except Exception as exc:  # noqa: BLE001 - evidence capture must not crash
                    snap["incident_error"] = str(exc)
                try:
                    snap["active_actions"] = http_get(
                        f"{args.executor}/audit/incidents/{args.incident_id}/active",
                        cg_env["CYBERGUARD_AUDIT_READER_TOKEN"],
                    )
                except Exception as exc:  # noqa: BLE001
                    snap["active_actions_error"] = str(exc)
                with (out / "service-snapshots.jsonl").open("a", encoding="utf-8") as sf:
                    sf.write(json.dumps(snap, ensure_ascii=False) + "\n")

    print(f"[capture] done, elapsed={round(time.monotonic() - started, 1)}s, events -> {events_path}")


if __name__ == "__main__":
    main()
