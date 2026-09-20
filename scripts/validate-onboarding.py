"""Isolated Linux/WSL transport acceptance: Docker Console -> UDS helper -> temporary HTTPS provider.

Requires Docker, openssl, Python 3.12+. No real provider or native team deployment.
"""
import argparse
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPCookieProcessor

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="cyberguard/operations-console:0.15.1")
    parser.add_argument("--port", type=int, default=18138)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/validation/onboarding/summary.json")
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        parser.error("Run as root in Linux or WSL2")
    identifier = secrets.token_hex(6)
    name = "cyberguard-onboarding-check-" + identifier
    volume = name + "-data"
    report = {"status": "failed", "image": args.image, "test": "real HTTPS and Unix socket transport with local provider stub",
        "real_provider_calls": 0, "native_team_deployment": False, "checks": [], "started_at_unix": time.time()}
    helper = None
    https_server = None
    container_created = volume_created = False
    stage = "prepare"

    def command(command, **kwargs):
        return subprocess.check_output(command, text=True, stderr=subprocess.PIPE, **kwargs).strip()

    def check(label, condition):
        report["checks"].append({"name": label, "passed": bool(condition)})
        if not condition:
            raise RuntimeError(label)

    try:
        with tempfile.TemporaryDirectory(prefix="cyberguard-onboarding-") as raw:
            root = Path(raw)
            runtime = root / "run"
            runtime.mkdir()
            os.chown(runtime, 0, 10003)
            os.chmod(runtime, 0o750)
            host_token = secrets.token_urlsafe(48)
            key = secrets.token_urlsafe(35)
            (runtime / "token").write_text(host_token)
            os.chown(runtime / "token", 0, 10003)
            os.chmod(runtime / "token", 0o640)
            certificate, private_key = root / "cert.pem", root / "key.pem"
            command(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1", "-keyout", str(private_key), "-out", str(certificate)])
            os.chmod(private_key, 0o600)
            requests = []

            class Provider(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass

                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    requests.append({"path": self.path, "authenticated": self.headers.get("Authorization") == "Bearer " + key,
                        "model": body.get("model"), "max_tokens": body.get("max_tokens")})
                    payload = json.dumps({"choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 1}}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

            https_server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, private_key)
            https_server.socket = context.wrap_socket(https_server.socket, server_side=True)
            threading.Thread(target=https_server.serve_forever, daemon=True).start()
            base_url = "https://127.0.0.1:" + str(https_server.server_address[1]) + "/v1"
            config = {"repo": str(ROOT), "private_dir": str(root / "private"), "plan": str(root / "plan"),
                "service_env": str(root / "service.env"), "token_file": str(runtime / "token"), "console_containers": [name]}
            config_path = root / "helper.json"
            config_path.write_text(json.dumps(config))
            os.chmod(config_path, 0o600)

            def start_helper():
                process = subprocess.Popen([sys.executable, str(ROOT / "deploy/onboarding/service.py"), "--config", str(config_path),
                    "--socket", str(runtime / "service.sock")], env=dict(os.environ, SSL_CERT_FILE=str(certificate)),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError("helper exited")
                    if (runtime / "service.sock").exists():
                        time.sleep(0.1)
                        return process
                    time.sleep(0.1)
                process.terminate()
                raise RuntimeError("helper readiness")

            helper = start_helper()
            command(["docker", "volume", "create", volume])
            volume_created = True
            command(["docker", "run", "-d", "--name", name, "--group-add", "10003", "-p", "127.0.0.1:" + str(args.port) + ":8080",
                "-v", volume + ":/data", "-v", str(runtime) + ":/run/cyberguard-onboarding:ro",
                "-e", "CYBERGUARD_COOKIE_SECURE=false", "-e", "CYBERGUARD_ONBOARDING_SOCKET=/run/cyberguard-onboarding/service.sock",
                "-e", "CYBERGUARD_ONBOARDING_TOKEN_FILE=/run/cyberguard-onboarding/token", args.image])
            container_created = True
            browser = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
            origin = "http://127.0.0.1:" + str(args.port)

            def request(path, form=None):
                req = Request(origin + path, data=urlencode(form).encode() if form is not None else None,
                    headers={"Content-Type": "application/x-www-form-urlencoded"} if form is not None else {})
                with browser.open(req, timeout=50) as response:
                    return response.geturl(), response.read().decode()

            stage = "first-admin-setup"
            for _ in range(60):
                try:
                    _, page = request("/setup")
                    break
                except OSError:
                    time.sleep(0.5)
            else:
                raise RuntimeError("Console readiness")
            csrf = re.search(r'name="login_csrf" value="([^"]+)"', page).group(1)
            setup_token = command(["docker", "exec", name, "python", "-c",
                "import sqlite3;print(sqlite3.connect('/data/console.db').execute(\"select setup_token from organization where id='default'\").fetchone()[0])"])
            password = secrets.token_urlsafe(24)
            final_url, page = request("/setup", {"login_csrf": csrf, "setup_token": setup_token,
                "username": "onboarding-validator", "password": password, "password_confirm": password})
            check("setup_automatically_logs_in_and_opens_wizard", final_url.endswith("/settings/onboarding") and 'id="model-form"' in page)
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
            stage = "model-https-probe"
            _, response = request("/settings/onboarding/test", {"csrf_token": csrf, "base_url": base_url, "model": "local-test-model", "api_key": key})
            check("real_https_probe_via_console_and_unix_socket", json.loads(response)["data"]["ok"] is True)
            check("one_bounded_authenticated_request", len(requests) == 1 and requests[0] == {
                "path": "/v1/chat/completions", "authenticated": True, "model": "local-test-model", "max_tokens": 32})
            check("probe_does_not_persist_key", not (root / "private/onboarding-model.json").exists())
            stage = "save-and-restart"
            _, saved = request("/settings/onboarding/save", {"csrf_token": csrf, "base_url": base_url, "model": "local-test-model", "api_key": key})
            check("save_succeeds_without_echoing_key", json.loads(saved)["data"]["saved"] and key not in saved)
            stored = root / "private/onboarding-model.json"
            check("private_file_mode_0600", stored.stat().st_mode & 0o777 == 0o600)
            check("private_key_round_trip", json.loads(stored.read_text())["api_key"] == key)
            _, status = request("/settings/onboarding/status")
            check("status_reports_has_key_without_secret", json.loads(status)["data"]["model"]["has_api_key"] and key not in status and host_token not in status)
            helper.terminate()
            helper.wait(timeout=10)
            (runtime / "service.sock").unlink(missing_ok=True)
            helper = start_helper()
            _, status = request("/settings/onboarding/status")
            check("helper_restart_preserves_saved_configuration", json.loads(status)["data"]["model"]["has_api_key"] and json.loads(status)["data"]["model"]["model"] == "local-test-model")
            check("no_extra_model_requests", len(requests) == 1)
            report.update(status="passed", local_https_requests=len(requests), checks_count=len(report["checks"]),
                image_id=command(["docker", "inspect", name, "--format", "{{.Image}}"]),
                tls_trust_scope="SSL_CERT_FILE only in isolated helper subprocess", installation_or_budget_actions=0)
    except Exception as exc:
        report.update(failed_stage=stage, error_type=type(exc).__name__)
    finally:
        if helper and helper.poll() is None:
            helper.terminate()
            helper.wait(timeout=10)
        if https_server:
            https_server.shutdown()
            https_server.server_close()
        if container_created:
            command(["docker", "rm", "-f", name])
        if volume_created:
            command(["docker", "volume", "rm", volume])
        report["elapsed_seconds"] = round(time.time() - report["started_at_unix"], 2)
        report["isolated_resources_removed"] = True
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary": str(args.out), "checks": len(report["checks"]), "failed_stage": report.get("failed_stage")}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
