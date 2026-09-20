"""Privileged local deployment bridge. No browser-selected commands or Docker socket forwarding."""
import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener, HTTPRedirectHandler


class Failure(Exception):
    def __init__(self, code, message, status=409):
        self.code, self.message, self.status = code, message, status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Failure("redirect_rejected", "Model endpoint redirects are not supported.", 422)


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + secrets.token_hex(5) + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value)
    os.replace(temp, path)
    os.chmod(path, 0o600)


class Service:
    def __init__(self, config):
        self.config = config
        self.repo = Path(config["repo"]).resolve()
        self.private = Path(config["private_dir"]).resolve()
        self.plan = Path(config["plan"]).resolve()
        self.service_env = Path(config["service_env"]).resolve()
        self.model_file = self.private / "onboarding-model.json"
        self.guard_file = self.private / "model-guard-config.json"
        self.token = Path(config["token_file"]).read_text().strip()
        if len(self.token) < 32:
            raise ValueError("Host service token must contain at least 32 characters")
        self.lock = threading.RLock()
        self.state = {"phase": "idle", "step": "", "error": None, "operation_id": None}

    def command(self, args, timeout=180):
        env = dict(os.environ, CYBERGUARD_AGENTTEAMS_SERVICE_ENV=str(self.service_env))
        # systemd does not inherit bootstrap's environment. Compose interpolation
        # must use the persisted host configuration on every invocation/restart.
        env["CYBERGUARD_ONBOARDING_RUN_DIR"] = self.config.get("run_dir", "/run/cyberguard-onboarding")
        origin = self.config.get("console_origin", "http://127.0.0.1:18120")
        env["CYBERGUARD_CONSOLE_ORIGIN"] = origin
        parsed = urlsplit(origin)
        env["CYBERGUARD_COOKIE_SECURE"] = "false" if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"} else "true"
        result = subprocess.run(args, cwd=self.repo, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=timeout)
        if result.returncode:
            # Subprocess logs can contain private routes/configuration. Do not return them to HTTP.
            raise Failure("deployment_step_failed", "Deployment step failed: " + self.state.get("step", "operation"), 502)
        return result.stdout

    def running(self, name):
        try:
            return self.command(["docker", "inspect", "--format", "{{.State.Running}}", name], 10).strip() == "true"
        except (Failure, OSError, subprocess.TimeoutExpired):
            return False

    def stored_model(self):
        if self.model_file.exists():
            return json.loads(self.model_file.read_text(encoding="utf-8"))
        if self.guard_file.exists():
            cfg = json.loads(self.guard_file.read_text(encoding="utf-8"))
            return {"base_url": cfg["upstream_endpoint"].removesuffix("/chat/completions"),
                    "model": cfg["model"], "api_key": cfg["upstream_key"]}
        return {}

    def model_input(self, body):
        old = self.stored_model()
        supplied_url = body.get("base_url")
        normalize = lambda value: value.strip().rstrip("/").removesuffix("/chat/completions")
        if supplied_url and isinstance(supplied_url, str) and not body.get("api_key") and old.get("api_key"):
            if normalize(supplied_url) != normalize(old.get("base_url", "")):
                raise Failure("new_endpoint_requires_key", "Enter the API key for the new endpoint; the previous provider key will not be reused.", 422)
        model = {k: body.get(k) or old.get(k, "") for k in ("base_url", "model", "api_key")}
        if any(not isinstance(v, str) or not v.strip() or len(v) > 4096 or "\n" in v or "\r" in v for v in model.values()):
            raise Failure("invalid_model", "Provide a base URL, model name and API key.", 422)
        model["base_url"] = model["base_url"].strip().rstrip("/").removesuffix("/chat/completions")
        url = urlsplit(model["base_url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise Failure("invalid_endpoint", "Use an HTTPS base URL without credentials, query or fragment. Put a TLS proxy in front of an HTTP-only service.", 422)
        return model

    def http(self, url, token, body=None, timeout=30):
        req = Request(url, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as response:
            return json.loads(response.read(1024 * 1024))

    def test_model(self, body):
        model = self.model_input(body)
        start = time.monotonic()
        try:
            result = self.http(model["base_url"] + "/chat/completions", model["api_key"],
                {"model": model["model"], "max_tokens": 32, "messages": [{"role": "user", "content": "Reply OK."}]}, 45)
            if not result.get("choices"):
                raise ValueError()
        except Exception:
            raise Failure("model_test_failed", "Model connection failed. Check endpoint, credentials and model availability.", 502) from None
        return {"ok": True, "model": model["model"], "latency_ms": round((time.monotonic() - start) * 1000)}

    def guard_status(self):
        cfg = json.loads(self.guard_file.read_text(encoding="utf-8"))
        return self.http(self.config.get("guard_url", "http://127.0.0.1:18112") + "/admin/status", cfg["admin_token"])

    def ensure_idle(self, require_closed=True):
        if not self.guard_file.exists():
            return
        try:
            status = self.guard_status()
        except Exception:
            raise Failure("guard_unavailable", "Cannot verify model service state. Restore the service before changing it.") from None
        if (require_closed and status["run"]["status"] == "open") or status.get("armed") or status["run"]["usage"]["concurrency_used"]:
            raise Failure("model_service_busy", "Close and drain the current model budget before changing deployment.")
        probe = ("import os,sqlite3; p=os.environ.get('CYBERGUARD_CONSOLE_DB','/data/console.db'); "
                 "c=sqlite3.connect('file:'+p+'?mode=ro',uri=True); "
                 "tables={r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")}; "
                 "print(c.execute(\"select count(*) from investigation_job where status in ('queued','running')\").fetchone()[0] if 'investigation_job' in tables else 0)")
        for name in self.config.get("console_containers", ["cyberguard-operations-console-1"]):
            if self.running(name):
                try:
                    active = int(self.command(["docker", "exec", name, "python", "-c", probe], 15).strip())
                except Exception:
                    raise Failure("queue_unavailable", "Cannot verify the Console queue. No deployment change was applied.") from None
                if active:
                    raise Failure("active_investigations", "Finish or cancel pending investigations before changing deployment.")

    def start_guard(self):
        self.command(["docker", "run", "-d", "--name", "cyberguard-native-model-guard", "--network", "agentteams-net",
            "--network-alias", "native-model-guard.agentteams.local", "--env-file", str(self.private / "model-guard.env"),
            "-e", "CYBERGUARD_DATA_DIR=/data", "-v", "cyberguard-native-model-budget:/data", "-p", "127.0.0.1:18112:8080",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "cyberguard/model-guard:native"])

    def wait_guard(self, run_id):
        for _ in range(30):
            try:
                status = self.guard_status()
                if status["run"]["run_id"] == run_id:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise Failure("guard_not_ready", "Model budget service did not pass its startup check.", 502)

    def restore_guard(self):
        if self.guard_file.exists() and not self.running("cyberguard-native-model-guard"):
            try:
                exists = bool(self.command(["docker", "inspect", "--format", "{{.Id}}", "cyberguard-native-model-guard"], 10).strip())
            except Failure:
                exists = False
            if exists:
                self.command(["docker", "start", "cyberguard-native-model-guard"])
            else:
                self.start_guard()
            self.wait_guard(json.loads(self.guard_file.read_text())["run_id"])

    def team_ready(self):
        try:
            manifest = json.loads((self.plan / "manifest.json").read_text())
            teams = json.loads(self.command(["docker", "exec", "agentteams-controller", "agt", "get", "teams", "-o", "json"], 15))["teams"]
            team = next(t for t in teams if t["name"] == manifest["team"])
            expected = {entry["worker"] for entry in manifest["roles"].values()}
            members = {entry["name"] for entry in team.get("workerMembers", [])}
            return (bool(team.get("leaderReady")) and expected <= members
                    and int(team.get("readyWorkers", 0)) >= len(expected - {team.get("leaderName")}))
        except Exception:
            return False

    def apply_model(self, model):
        if not self.guard_file.exists():
            return False
        cfg = json.loads(self.guard_file.read_text(encoding="utf-8"))
        if (cfg["model"], cfg["upstream_endpoint"], cfg["upstream_key"]) == (model["model"], model["base_url"] + "/chat/completions", model["api_key"]):
            return True
        self.ensure_idle()
        # ModelGuard binds configuration immutably to a run. Preserve old ledger, use a fresh run.
        previous = json.loads(json.dumps(cfg))
        private_write(self.private / "model-guard.previous.json", json.dumps(previous))
        def write_config(value):
            private_write(self.guard_file, json.dumps(value))
            private_write(self.private / "model-guard.env", "CYBERGUARD_MODEL_GUARD_CONFIG=" + json.dumps(value, separators=(",", ":")) + "\n")
        cfg.update(run_id="CG-MODEL-" + secrets.token_hex(10), model=model["model"],
                   upstream_endpoint=model["base_url"] + "/chat/completions", upstream_key=model["api_key"])
        try:
            write_config(cfg)
            self.command(["docker", "stop", "cyberguard-native-model-guard"])
            self.command(["docker", "rm", "cyberguard-native-model-guard"])
            self.start_guard()
            self.wait_guard(cfg["run_id"])
        except Exception:
            write_config(previous)
            self.state.update(phase="failed", error="Model update failed. Previous configuration restored; verify model service availability.")
            try:
                for command in (["docker", "stop", "cyberguard-native-model-guard"], ["docker", "rm", "cyberguard-native-model-guard"]):
                    try:
                        self.command(command)
                    except Failure:
                        pass
                self.start_guard()
                self.wait_guard(previous["run_id"])
            except Exception:
                pass
            raise Failure("model_update_failed", self.state["error"], 502) from None
        return True

    def save_model(self, body):
        with self.lock:
            if self.state["phase"] == "initializing":
                raise Failure("initializing", "Wait for initialization to finish.")
            model = self.model_input(body)
            applied = self.apply_model(model) if body.get("apply") is True else False
            private_write(self.model_file, json.dumps(model))
            if applied:
                self.state.update(phase="idle", step="model-applied", error=None)
            return {"saved": True, "applied": applied, "restart_required": self.guard_file.exists() and not applied}

    def status(self):
        model = self.stored_model()
        result = {**self.state, "model": {"configured": bool(model), "base_url": model.get("base_url", ""),
            "model": model.get("model", ""), "has_api_key": bool(model.get("api_key")), "pending_apply": False},
            "deployment": {"prepared": self.guard_file.exists(), "controller_running": self.running("agentteams-controller"),
                           "guard_running": self.running("cyberguard-native-model-guard")}}
        result["deployment"]["team_ready"] = self.team_ready() if result["deployment"]["controller_running"] else False
        if (self.plan / "runtime-ready.json").exists() and result["phase"] in {"idle", "ready"} and all(
                result["deployment"][k] for k in ("controller_running", "guard_running", "team_ready")):
            result["phase"] = "ready"
        elif result["phase"] == "ready":
            result["phase"] = "idle"
        if self.guard_file.exists() and model:
            cfg = json.loads(self.guard_file.read_text())
            result["model"]["pending_apply"] = (cfg["model"], cfg["upstream_endpoint"], cfg["upstream_key"]) != (
                model["model"], model["base_url"] + "/chat/completions", model["api_key"])
        try:
            guard = self.guard_status()
            cfg = json.loads(self.guard_file.read_text(encoding="utf-8"))
            result["budget"] = {"armed": guard.get("armed", False), "status": guard["run"]["status"],
                                "limits": cfg["limits"], "usage": guard["run"]["usage"], "run_id": cfg["run_id"]}
        except Exception:
            result["budget"] = {"armed": False, "status": "unavailable"}
        return result

    def open_budget(self):
        with self.lock:
            if self.state["phase"] == "initializing":
                raise Failure("initializing", "Wait for initialization to finish.")
            if not self.guard_file.exists():
                raise Failure("initialization_required", "Initialize the investigation service first.")
            cfg = json.loads(self.guard_file.read_text())
            model = self.stored_model()
            if (cfg["model"], cfg["upstream_endpoint"], cfg["upstream_key"]) != (model["model"], model["base_url"] + "/chat/completions", model["api_key"]):
                raise Failure("model_update_pending", "Initialize the saved model configuration before enabling investigations.")
            try:
                status = self.guard_status()
            except Exception:
                raise Failure("initialization_required", "The model service is unavailable; initialize it first.") from None
            if status["run"]["status"] == "open" and status.get("armed"):
                return {"armed": True, "reused": True, "run_id": json.loads(self.guard_file.read_text())["run_id"]}
            if status["run"]["usage"]["concurrency_used"]:
                raise Failure("model_service_busy", "Wait for outstanding model requests to finish.")
            if status["run"]["status"] == "closed":
                self.command([sys.executable, "deploy/investigation-service/budget.py", "new-run", "--private-dir", str(self.private),
                    "--url", self.config.get("guard_url", "http://127.0.0.1:18112"), "--run-id", "CG-WEB-" + secrets.token_hex(10)])
            cfg = json.loads(self.guard_file.read_text())
            last = None
            for _ in range(20):
                try:
                    result = self.http(self.config.get("guard_url", "http://127.0.0.1:18112") + "/admin/arm", cfg["admin_token"], {})
                    return {"armed": result.get("armed", True), "reused": False, "run_id": cfg["run_id"], "limits": cfg["limits"]}
                except Exception as exc:
                    last = exc
                    time.sleep(0.5)
            raise Failure("budget_open_failed", "The budget service did not become ready. Existing ledger was preserved.", 502) from None

    def initialize(self):
        with self.lock:
            if self.state["phase"] == "initializing":
                return {"operation_id": self.state["operation_id"], "phase": "initializing"}
            self.model_input({})
            if self.running("cyberguard-native-model-guard"):
                self.ensure_idle(require_closed=False)
            self.state = {"phase": "initializing", "step": "preflight", "error": None, "operation_id": secrets.token_hex(12)}
            threading.Thread(target=self.provision, daemon=True).start()
            return {"operation_id": self.state["operation_id"], "phase": "initializing"}

    def wait_workers(self, workers):
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            if all(self.running("agentteams-worker-" + name) for name in workers):
                try:
                    for name in workers:
                        self.command(["docker", "exec", "agentteams-worker-" + name, "/opt/venv/qwenpaw/bin/python", "-c",
                            "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8088/api/agents/default',timeout=3)"], 10)
                    return
                except Failure:
                    pass
            time.sleep(5)
        raise Failure("workers_not_ready", "Workers did not become ready within six minutes.", 502)

    def provision(self):
        def step(name, args, timeout=180):
            self.state["step"] = name
            return self.command(args, timeout)
        py = sys.executable
        native = "deploy/investigation-service/"
        local = "deploy/agentteams-local/"
        try:
            model = self.model_input({})
            model_env = self.private / "onboarding-model.env"
            private_write(model_env, "AGENTTEAMS_DEFAULT_MODEL=" + model["model"] + "\nAGENTTEAMS_OPENAI_BASE_URL=" + model["base_url"] + "\nAGENTTEAMS_LLM_API_KEY=" + model["api_key"] + "\n")
            self.state["step"] = "restore-model-service"
            self.restore_guard()
            self.ensure_idle(require_closed=False)
            if not self.running("agentteams-controller"):
                try:
                    existing = bool(self.command(["docker", "inspect", "--format", "{{.Id}}", "agentteams-controller"], 15).strip())
                except Failure:
                    existing = False
                if existing:
                    step("resume-controller", ["docker", "start", "agentteams-controller"])
                    deadline = time.monotonic() + 360
                    while time.monotonic() < deadline:
                        try:
                            self.command(["docker", "exec", "agentteams-controller", "agt", "get", "workers", "-o", "json"], 15)
                            break
                        except Failure:
                            time.sleep(5)
                    else:
                        raise Failure("controller_not_ready", "Existing controller did not become ready.", 502)
            if not self.running("agentteams-controller"):
                step("prepare-platform", [py, local + "prepare-local.py", "--directory", str(self.service_env.parent)])
                step("prepare-network", [py, local + "ensure-private-network.py"])
                step("build-controller", ["bash", native + "build-controller.sh"], 3600)
                step("build-model-service", ["docker", "build", "-f", "services/model-guard/Dockerfile", "-t", "cyberguard/model-guard:native", "."], 900)
                step("start-controller", ["docker", "compose", "-f", native + "compose.native.yaml", "up", "-d", "--wait", "--wait-timeout", "360"], 420)
            if not self.guard_file.exists():
                try:
                    self.command(["docker", "image", "inspect", "cyberguard/model-guard:native"], 15)
                except Failure:
                    step("build-model-service", ["docker", "build", "-f", "services/model-guard/Dockerfile", "-t", "cyberguard/model-guard:native", "."], 900)
                step("prepare-team", [py, native + "prepare-native-team.py", "--private-dir", str(self.private), "--plan", str(self.plan),
                    "--model-env", str(model_env), "--run-id", "CG-SETUP-" + self.state["operation_id"], "--name-prefix", self.config.get("name_prefix", "cg-native001")])
            else:
                self.state["step"] = "apply-model"
                self.apply_model(model)
            if not (self.plan / "runtime-ready.json").exists() or not self.team_ready():
                if not (self.plan / "deployment.json").exists():
                    marker = self.private / "onboarding-routes-registered.json"
                    if not marker.exists():
                        step("register-routes", [py, local + "register-guarded-routes.py", "--plan", str(self.plan), "--guard-env", str(self.private / "model-guard.env")])
                        private_write(marker, json.dumps({"plan": str(self.plan)}))
                    step("create-team", [py, local + "apply-guarded-team.py", "--plan", str(self.plan), "--out", str(self.plan / "deployment.json")])
                manifest = json.loads((self.plan / "manifest.json").read_text())
                workers = [entry["worker"] for entry in manifest["roles"].values()]
                for worker in workers:
                    step("wake-workers", ["docker", "exec", "agentteams-controller", "agt", "worker", "wake", "--name", worker])
                self.state["step"] = "wait-workers"
                self.wait_workers(workers)
                step("install-collaboration", [py, native + "install-collaboration.py", "--manifest", str(self.plan / "manifest.json")], 300)
                step("restart-workers", ["docker", "restart", *["agentteams-worker-" + w for w in workers]], 180)
                self.wait_workers(workers)
                step("configure-team", [py, native + "configure-native-team.py", "--private-dir", str(self.private), "--plan", str(self.plan),
                    "--service-env", str(self.service_env), "--console-origin", self.config.get("console_origin", "http://127.0.0.1:18120")], 300)
            command = ["docker", "compose", "-f", "compose.yaml", "-f", str(self.private / "console.override.json")]
            for overlay in self.config.get("compose_overlays", []):
                command += ["-f", str(Path(overlay).resolve())]
            step("connect-console", command + ["up", "-d", "--no-deps", "operations-console"], 180)
            if not self.team_ready():
                raise Failure("team_not_ready", "The native team has not reached ready state.", 502)
            self.state.update(phase="ready", step="complete", error=None)
        except Exception as exc:
            message = exc.message if isinstance(exc, Failure) else "Installation failed at " + self.state["step"] + ". Check host prerequisites and retry."
            self.state.update(phase="failed", error=message)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, status, value):
        raw = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_request(self):
        service = self.server.service
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + service.token).encode()):
            return self.send_json(401, {"error": {"code": "unauthorized", "message": "Host service authentication required."}})
        try:
            path = self.path.removeprefix("/v1")
            if self.command == "GET" and path == "/status":
                return self.send_json(200, {"data": service.status()})
            length = int(self.headers.get("Content-Length", "0"))
            if self.command != "POST" or length > 16384 or length < 0:
                raise Failure("invalid_request", "Unsupported request.", 400)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise Failure("invalid_request", "Expected a JSON object.", 422)
            routes = {"/model/test": service.test_model, "/model/save": service.save_model,
                      "/initialize": lambda _: service.initialize(), "/budget/open": lambda _: service.open_budget()}
            if path not in routes:
                raise Failure("not_found", "Unknown operation.", 404)
            result = routes[path](body)
            self.send_json(202 if path == "/initialize" else 200, {"data": result})
        except Failure as exc:
            self.send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except Exception:
            self.send_json(500, {"error": {"code": "operation_failed", "message": "Operation failed; no private diagnostic data is returned."}})

    do_GET = handle_request
    do_POST = handle_request


class UnixServer(socketserver.ThreadingMixIn, getattr(socketserver, "UnixStreamServer", socketserver.TCPServer)):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "::1"])
    parser.add_argument("--port", type=int, default=18140)
    args = parser.parse_args()
    service = Service(json.loads(args.config.read_text()))
    if args.socket:
        if args.socket.exists():
            args.socket.unlink()
        server = UnixServer(str(args.socket), Handler)
        os.chown(args.socket, -1, 10003)
        os.chmod(args.socket, 0o660)
    else:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.service = service
    server.serve_forever()


if __name__ == "__main__":
    main()
