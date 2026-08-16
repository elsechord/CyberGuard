#!/usr/bin/env python3
"""Send one hash-bound, idempotent bootstrap request to AgentTeams Manager over Matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import parse, request


ROOT = Path(__file__).resolve().parents[1]
COMPLETE_MARKER = "CYBERGUARD_BOOTSTRAP_COMPLETE"


class MatrixClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def call(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(self.base_url + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
        })
        with request.urlopen(req, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))

    def sync(self, since: str | None = None, timeout_ms: int = 0) -> dict[str, Any]:
        query = {"timeout": str(timeout_ms)}
        if since:
            query["since"] = since
        return self.call("GET", "/_matrix/client/v3/sync?" + parse.urlencode(query))

    def send(self, room_id: str, body: str) -> str:
        room = parse.quote(room_id, safe="")
        result = self.call("PUT", f"/_matrix/client/v3/rooms/{room}/send/m.room.message/{uuid.uuid4().hex}", {
            "msgtype": "m.text", "body": body,
        })
        return str(result["event_id"])


def login(base_url: str, username: str, password: str) -> tuple[str, str]:
    payload = {
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": username},
        "password": password,
    }
    req = request.Request(base_url.rstrip("/") + "/_matrix/client/v3/login",
                          data=json.dumps(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=45) as response:
        result = json.loads(response.read().decode())
    return str(result["access_token"]), str(result["user_id"])


def find_manager_room(client: MatrixClient, admin_user_id: str) -> tuple[str, str]:
    candidates: list[tuple[str, str]] = []
    for room_id in client.call("GET", "/_matrix/client/v3/joined_rooms").get("joined_rooms", []):
        room = parse.quote(str(room_id), safe="")
        members = client.call("GET", f"/_matrix/client/v3/rooms/{room}/members").get("chunk", [])
        joined = [str(item.get("state_key", "")) for item in members
                  if item.get("content", {}).get("membership") == "join"]
        managers = [member for member in joined if member != admin_user_id
                    and "manager" in member.split(":", 1)[0].lower()]
        if len(managers) == 1 and len(joined) <= 3:
            candidates.append((str(room_id), managers[0]))
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one Manager DM room, found {len(candidates)}")
    return candidates[0]


def build_request(source: Path, bundle_manifest: Path | None = None) -> tuple[str, str, str | None]:
    body = source.read_text(encoding="utf-8")
    digest = hashlib.sha256(body.encode()).hexdigest()
    bundle_digest = hashlib.sha256(bundle_manifest.read_bytes()).hexdigest() if bundle_manifest else None
    bundle_line = f"CYBERGUARD_BOOTSTRAP_BUNDLE_SHA256={bundle_digest}\n" if bundle_digest else ""
    envelope = f"CYBERGUARD_BOOTSTRAP_REQUEST_SHA256={digest}\n{bundle_line}\n{body}"
    return envelope, digest, bundle_digest


def wait_for_completion(client: MatrixClient, room_id: str, manager_id: str,
                        since: str, timeout_seconds: int) -> tuple[str, str]:
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        update = client.sync(since=since, timeout_ms=min(30_000, timeout_seconds * 1000))
        since = str(update["next_batch"])
        events = update.get("rooms", {}).get("join", {}).get(room_id, {}).get("timeline", {}).get("events", [])
        for event in events:
            if event.get("sender") != manager_id or event.get("type") != "m.room.message":
                continue
            body = str(event.get("content", {}).get("body", ""))
            if COMPLETE_MARKER in body:
                return str(event.get("event_id", "")), body
    raise TimeoutError(f"Manager did not emit {COMPLETE_MARKER} within {timeout_seconds}s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("MATRIX_BASE_URL", "http://127.0.0.1:18080"))
    parser.add_argument("--username", default=os.getenv("MATRIX_USERNAME"))
    parser.add_argument("--password", default=os.getenv("MATRIX_PASSWORD"))
    parser.add_argument("--request", type=Path, default=ROOT / "agentteams" / "bootstrap-manager-request.md")
    parser.add_argument("--bundle-manifest", type=Path)
    parser.add_argument("--evidence", type=Path, default=ROOT / "artifacts" / "agentteams-bootstrap.json")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    message, digest, bundle_digest = build_request(args.request, args.bundle_manifest)
    if args.dry_run:
        print(json.dumps({"valid": True, "request_sha256": digest,
                          "bundle_sha256": bundle_digest, "characters": len(message)}, indent=2))
        return 0
    if not args.username or not args.password:
        raise SystemExit("Provide MATRIX_USERNAME/MATRIX_PASSWORD or the corresponding options")
    token, admin_user_id = login(args.base_url, args.username, args.password)
    client = MatrixClient(args.base_url, token)
    room_id, manager_id = find_manager_room(client, admin_user_id)
    since = str(client.sync(timeout_ms=0)["next_batch"])
    request_event_id = client.send(room_id, message)
    reply_event_id, reply = wait_for_completion(client, room_id, manager_id, since, args.timeout)
    evidence = {
        "schema_version": 1, "request_sha256": digest, "bundle_sha256": bundle_digest,
        "room_id": room_id,
        "manager_id": manager_id, "request_event_id": request_event_id,
        "reply_event_id": reply_event_id, "completion_marker": COMPLETE_MARKER,
        "reply_sha256": hashlib.sha256(reply.encode()).hexdigest(),
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Manager bootstrap completed; evidence: {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
