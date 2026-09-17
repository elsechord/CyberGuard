"""Real HTTP lab stack shared by integration tests and the deterministic demo."""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


def http(url, token=None, body=None, headers=None):
    fields = {"Content-Type": "application/json", **(headers or {})}
    if token:
        fields["Authorization"] = "Bearer " + token
    request = Request(url, headers=fields, data=json.dumps(body).encode() if body is not None else None)
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.code, json.loads(response.read())


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LabStack:
    def __init__(self, directory=None):
        self.temp = tempfile.TemporaryDirectory() if directory is None else None
        self.directory = Path(self.temp.name if self.temp else directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ports = {name: free_port() for name in ("identity", "executor", "gateway")}
        while len(set(self.ports.values())) < 3:
            self.ports = {name: free_port() for name in self.ports}
        self.urls = {name: f"http://127.0.0.1:{port}" for name, port in self.ports.items()}
        self.tokens = {key: secrets.token_urlsafe(36) for key in
                       ("admin", "target", "control", "executor", "approval", "audit", "audit_reader", "gateway")}
        self.processes = {}
        self.logs = {}
        self.overrides = {}

    def environment(self, role):
        env = {k: v for k, v in os.environ.items() if not k.startswith("CYBERGUARD_")}
        env.update(PYTHONUNBUFFERED="1", PYTHONUTF8="1")
        if role == "identity":
            names = {"LAB_ADMIN_TOKEN": "admin", "LAB_TARGET_TOKEN": "target", "LAB_CONTROL_TOKEN": "control"}
        elif role == "executor":
            names = {"EXECUTOR_TOKEN": "executor", "APPROVAL_SECRET": "approval", "AUDIT_HMAC_KEY": "audit",
                     "AUDIT_READER_TOKEN": "audit_reader", "LAB_ADMIN_TOKEN": "admin"}
            env.update(CYBERGUARD_EXECUTION_MODE="lab", CYBERGUARD_LAB_URL=self.urls["identity"],
                       CYBERGUARD_DATA_DIR=str(self.directory / "executor"))
        else:
            names = {"API_TOKEN": "gateway", "AUDIT_READER_TOKEN": "audit_reader",
                     "LAB_TARGET_TOKEN": "target", "LAB_CONTROL_TOKEN": "control"}
            env.update(CYBERGUARD_LAB_URL=self.urls["identity"],
                       CYBERGUARD_AUDIT_VERIFY_URL=self.urls["executor"],
                       CYBERGUARD_DATA_DIR=str(self.directory / "gateway"),
                       CYBERGUARD_SCENARIO_DIR=str(ROOT / "scenarios"),
                       CYBERGUARD_KNOWLEDGE_DIR=str(ROOT / "knowledge"))
        env.update({"CYBERGUARD_" + name: self.tokens[key] for name, key in names.items()})
        env.update(self.overrides.get(role, {}))
        return env

    def command(self, role):
        port = str(self.ports[role])
        if role == "identity":
            command = [sys.executable, str(ROOT / "services/lab-identity/server.py"),
                       "--db", str(self.directory / "identity.sqlite"), "--port", port]
        else:
            service = "response-executor" if role == "executor" else "security-tool-gateway"
            command = [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "services" / service),
                       "--host", "127.0.0.1", "--port", port, "--workers", "1", "--no-access-log"]
        return command

    def start(self, role):
        command = self.command(role)
        log = (self.directory / (role + ".log")).open("ab")
        self.logs[role] = log
        self.processes[role] = subprocess.Popen(command, cwd=ROOT, env=self.environment(role),
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.processes[role].poll() is not None:
                raise RuntimeError(f"{role} exited; inspect its local log")
            try:
                status, _ = http(self.urls[role] + "/health")
                if status == 200:
                    return
            except (URLError, OSError):
                pass
            time.sleep(0.1)
        raise RuntimeError(f"{role} readiness timeout")

    def stop(self, role):
        process = self.processes.pop(role, None)
        if process:
            # Windows venv python.exe can be a redirector with a child Python.
            # Terminate our own process tree so that child servers do not leak.
            if os.name == "nt" and process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, check=True)
            elif process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log = self.logs.pop(role, None)
        if log:
            log.close()

    def __enter__(self):
        try:
            for role in self.ports:
                self.start(role)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        for role in reversed(self.ports):
            self.stop(role)
        if self.temp:
            self.temp.cleanup()

    def call(self, path, body=None, approval=False):
        headers = {"X-Approval-Secret": self.tokens["approval"]} if approval else {}
        return http(self.urls["executor"] + path, self.tokens["executor"], body, headers)

    def propose(self, run_id):
        return self.call("/actions/propose", {
            "incident_id": "CG-LAB-001", "run_id": run_id, "model_mode": "deterministic",
            "action": "disable_account", "target": "compromised-lab",
            "reason": "Laboratory account containment with independent access probes.",
            "idempotency_key": run_id + "-disable"})

    def approve(self, action):
        return self.call("/actions/approve", {"action_id": action["action_id"], "approver": "lab-operator"}, True)

    def verify(self, action, run_id=None):
        return http(self.urls["gateway"] + "/tools/recovery/metrics", self.tokens["gateway"], {
            "incident_id": action["incident_id"], "scenario_id": "lab_identity",
            "arguments": {"run_id": run_id or action["run_id"], "action_id": action["action_id"]}})
