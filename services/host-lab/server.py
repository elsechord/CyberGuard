"""Isolated Linux process laboratory; no shell, host mounts, malware or network traffic."""
import argparse
import hashlib
import hmac
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4


def now():
    return datetime.now(UTC).isoformat()


class Lab:
    RESTART_SECONDS = 1.0

    def __init__(self, directory):
        if sys.platform != "linux" or not hasattr(os, "pidfd_open"):
            raise RuntimeError("host lab requires Linux with pidfd support")
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.environment_id = "HOST-" + uuid4().hex
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.processes = {}
        self.events = []
        self.last_mutation = None
        self.worker = Path(__file__).with_name("worker.py")
        self.persistence = directory / "compute-supervisor.json"
        self.persistence.write_text(json.dumps({"schema": "cyberguard-benign-supervisor/v1",
            "environment_id": self.environment_id, "worker_sha256": self.file_hash(self.worker),
            "restart_seconds": self.RESTART_SECONDS}), encoding="utf-8")
        self.db = sqlite3.connect(directory / "operations.sqlite", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, request TEXT, receipt TEXT)")
        self.db.commit()
        self.spawn("control")
        self.spawn("compute")
        self.thread = threading.Thread(target=self.supervise, daemon=True)
        self.thread.start()

    @staticmethod
    def file_hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def log(self, kind, **fields):
        event = {"observed_at": now(), "event": kind, **fields}
        self.events.append(event)
        with (self.directory / "supervisor.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def spawn(self, role):
        previous = self.processes.get(role)
        if previous:
            previous.wait(timeout=2)
        process = subprocess.Popen([sys.executable, str(self.worker), "--role", role,
            "--heartbeat", str(self.directory / (role + ".json"))], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        self.processes[role] = process
        self.log("process_started", role=role, pid=process.pid,
                 cause="supervisor" if previous else "lab_provisioning")

    def supervise(self):
        while not self.stop.wait(self.RESTART_SECONDS):
            with self.lock:
                if self.persistence.exists() and self.processes["compute"].poll() is not None:
                    self.spawn("compute")

    def process(self, role):
        child = self.processes[role]
        if child.poll() is not None:
            return None
        directory = Path("/proc") / str(child.pid)
        # /proc stat comm may contain spaces/parentheses. Field 22 is starttime.
        stat = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        identity = {"environment_id": self.environment_id, "pid": child.pid,
                    "start_ticks": stat[19], "executable_sha256": self.file_hash(directory / "exe"),
                    "worker_sha256": self.file_hash(self.worker)}
        target = "process:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        heartbeat = None
        try:
            heartbeat = json.loads((self.directory / (role + ".json")).read_text())
            if heartbeat.get("pid") != child.pid:
                heartbeat = None
        except (OSError, ValueError):
            pass
        return {**identity, "target_ref": target, "role": role, "parent_pid": int(stat[1]),
                "command_line": (directory / "cmdline").read_bytes().decode().split("\0")[:-1],
                "heartbeat": heartbeat}

    def persistence_state(self):
        if not self.persistence.exists():
            return {"present": False, "path": str(self.persistence)}
        content = self.persistence.read_text(encoding="utf-8")
        digest = hashlib.sha256(content.encode()).hexdigest()
        return {"present": True, "path": str(self.persistence), "sha256": digest,
                "target_ref": "persistence:" + self.environment_id + ":" + digest,
                "content": content}

    def snapshot(self, nonce):
        with self.lock:
            return {"environment_id": self.environment_id, "environment": "lab", "execution": "real",
                "scenario_nature": "benign_process_emulation", "nonce": nonce, "observed_at": now(),
                "processes": [p for role in ("compute", "control") if (p := self.process(role))],
                "persistence": self.persistence_state(), "events": self.events[-32:],
                "last_mutation": self.last_mutation,
                "restart_interval_seconds": self.RESTART_SECONDS,
                "limitations": ["No actual miner, initial exploit, network beacon or adversary identity.",
                                "The collector and workload share a trusted laboratory boundary."]}

    def terminate(self, role):
        process = self.processes[role]
        if process.poll() is None:
            fd = os.pidfd_open(process.pid)
            try:
                signal.pidfd_send_signal(fd, signal.SIGTERM)
                process.wait(timeout=2)
            finally:
                os.close(fd)
            self.log("process_stopped", role=role, pid=process.pid)

    def operation(self, operation_id, request):
        canonical = json.dumps(request, sort_keys=True)
        with self.lock:
            row = self.db.execute("SELECT request, receipt FROM operations WHERE id=?", (operation_id,)).fetchone()
            if row:
                if row[0] != canonical:
                    return 409, {"error": "operation_id_binding_conflict"}
                return 200, json.loads(row[1])
            if (set(request) != {"kind", "target", "action_id", "run_id", "environment_id"}
                    or request.get("kind") not in {"terminate_process", "disable_persistence"}
                    or not all(isinstance(v, str) and 1 <= len(v) <= 512 for v in request.values())
                    or request["action_id"] != operation_id):
                return 422, {"error": "invalid_operation"}
            receipt = {**request, "operation_id": operation_id, "observed_at": now(), "result": "unknown"}
            current = self.process("compute") if request["kind"] == "terminate_process" else self.persistence_state()
            valid = (request["environment_id"] == self.environment_id and current
                     and request["target"] == current.get("target_ref"))
            if not valid:
                receipt.update(result="rejected", reason="target_precondition_changed_or_not_allowed")
            # Durable unknown intent comes before side effects. A crash cannot
            # make a retry issue a second process signal or delete a new file.
            self.db.execute("INSERT INTO operations VALUES (?,?,?)", (operation_id, canonical, json.dumps(receipt)))
            self.db.commit()
            if valid:
                self.last_mutation = {"action_id": request["action_id"], "run_id": request["run_id"], "result": "unknown"}
                if request["kind"] == "disable_persistence":
                    self.persistence.replace(self.directory / (operation_id + ".quarantined.json"))
                    self.log("supervisor_disabled", operation_id=operation_id)
                self.terminate("compute")
                receipt.update(result="applied")
                self.db.execute("UPDATE operations SET receipt=? WHERE id=?", (json.dumps(receipt), operation_id))
                self.db.commit()
                self.last_mutation["result"] = "applied"
            return 200, receipt

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)
        with self.lock:
            for role in self.processes:
                self.terminate(role)
            self.db.close()


def handler(lab, admin, reader):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, payload):
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self, token):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/health":
                return self.send(200, {"status": "ok", "environment": "lab", "backend": "host_lab",
                                       "environment_id": lab.environment_id})
            if parsed.path == "/snapshot":
                if not self.authorized(reader):
                    return self.send(401, {"error": "unauthorized"})
                nonce = parse_qs(parsed.query).get("nonce", [""])[0]
                if not 16 <= len(nonce) <= 64:
                    return self.send(422, {"error": "nonce_required"})
                return self.send(200, lab.snapshot(nonce))
            if not self.authorized(admin):
                return self.send(401, {"error": "unauthorized"})
            with lab.lock:
                row = lab.db.execute("SELECT receipt FROM operations WHERE id=?", (parsed.path.removeprefix("/operations/"),)).fetchone()
            return self.send(200 if row else 404, json.loads(row[0]) if row else {"error": "not_found"})

        def do_POST(self):
            if not self.authorized(admin):
                return self.send(401, {"error": "unauthorized"})
            operation_id = self.path.removeprefix("/operations/")
            if not self.path.startswith("/operations/") or not operation_id.isascii() or not operation_id.replace("-", "").isalnum() or len(operation_id) > 128:
                return self.send(404, {"error": "not_found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError()
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, TypeError):
                return self.send(422, {"error": "invalid_body"})
            status, result = lab.operation(operation_id, body)
            self.send(status, result)
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    admin = os.environ["CYBERGUARD_HOST_ADMIN_TOKEN"]
    reader = os.environ["CYBERGUARD_HOST_READER_TOKEN"]
    if min(len(admin), len(reader)) < 32 or admin == reader:
        raise RuntimeError("distinct admin and reader credentials of at least 32 characters required")
    lab = Lab(args.directory)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(lab, admin, reader))
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        lab.close()
