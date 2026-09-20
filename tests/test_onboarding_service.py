import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location("onboarding_service", Path(__file__).resolve().parents[1] / "deploy/onboarding/service.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OnboardingServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        token = self.root / "token"
        token.write_text("x" * 48)
        self.service = module.Service({"repo": str(self.root), "private_dir": str(self.root / "private"),
            "plan": str(self.root / "plan"), "service_env": str(self.root / "service.env"), "token_file": str(token)})
        self.model = {"base_url": "https://model.example/v1", "model": "test-model", "api_key": "unit-test-private-key"}

    def guard(self):
        config = {"upstream_endpoint": "https://old.example/v1/chat/completions", "upstream_key": "old-private",
            "model": "old", "run_id": "preserved-run", "roles": {"investigator": {"token": "role-private", "model_alias": "alias"}},
            "admin_token": "admin-private", "limits": {"max_requests": 120}}
        module.private_write(self.service.guard_file, json.dumps(config))
        return config

    def test_save_is_private_and_does_not_execute_docker(self):
        with patch.object(self.service, "command") as command:
            result = self.service.save_model(self.model)
        command.assert_not_called()
        self.assertEqual(result, {"saved": True, "applied": False, "restart_required": False})
        self.assertNotIn(self.model["api_key"], json.dumps(result))
        if os.name == "posix":
            self.assertEqual(self.service.model_file.stat().st_mode & 0o777, 0o600)

    def test_compose_environment_comes_from_config_without_bootstrap_environment(self):
        self.service.config.update(run_dir="/run/custom cyberguard", console_origin="http://localhost:18125")
        result = type("Completed", (), {"returncode": 0, "stdout": "ok"})()
        with patch.dict(os.environ, {"CYBERGUARD_ONBOARDING_RUN_DIR": "/stale", "CYBERGUARD_CONSOLE_ORIGIN": "https://stale.example", "CYBERGUARD_COOKIE_SECURE": "true"}), patch.object(module.subprocess, "run", return_value=result) as run:
            self.service.command(["docker", "compose", "config"])
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["CYBERGUARD_ONBOARDING_RUN_DIR"], "/run/custom cyberguard")
        self.assertEqual(env["CYBERGUARD_CONSOLE_ORIGIN"], "http://localhost:18125")
        self.assertEqual(env["CYBERGUARD_COOKIE_SECURE"], "false")
        self.service.config["console_origin"] = "https://console.example"
        with patch.object(module.subprocess, "run", return_value=result) as run:
            self.service.command(["docker", "compose", "config"])
        self.assertEqual(run.call_args.kwargs["env"]["CYBERGUARD_COOKIE_SECURE"], "true")

    def test_existing_configuration_is_read_without_change_or_secret_return(self):
        self.guard()
        before = self.service.guard_file.read_bytes()
        with patch.object(self.service, "running", return_value=True), patch.object(self.service, "guard_status", side_effect=OSError):
            status = self.service.status()
        self.assertEqual(status["model"]["model"], "old")
        self.assertTrue(status["model"]["has_api_key"])
        self.assertNotIn("old-private", json.dumps(status))
        self.assertEqual(before, self.service.guard_file.read_bytes())

    def test_update_preserves_role_credentials_and_run_id(self):
        old = self.guard()
        with patch.object(self.service, "ensure_idle"), patch.object(self.service, "wait_guard"), patch.object(self.service, "command") as command:
            self.service.save_model({**self.model, "apply": True})
        new = json.loads(self.service.guard_file.read_text())
        for field in ("roles", "admin_token", "limits"):
            self.assertEqual(old[field], new[field])
        self.assertNotEqual(old["run_id"], new["run_id"])
        self.assertEqual(new["model"], "test-model")
        commands = [call.args[0] for call in command.call_args_list]
        self.assertFalse(any("volume" in args for args in commands))

    def test_failed_rebuild_restores_private_configuration(self):
        old = self.guard()
        with patch.object(self.service, "ensure_idle"), patch.object(self.service, "running", return_value=True), patch.object(
                self.service, "command", side_effect=module.Failure("failed", "test failure")):
            with self.assertRaises(module.Failure):
                self.service.save_model({**self.model, "apply": True})
        self.assertEqual(json.loads(self.service.guard_file.read_text()), old)
        self.assertEqual(self.service.state["phase"], "failed")
        self.assertFalse(self.service.model_file.exists())

    def test_saved_model_reports_pending_apply(self):
        self.guard()
        self.service.save_model(self.model)
        with patch.object(self.service, "running", return_value=True), patch.object(self.service, "guard_status", side_effect=OSError):
            status = self.service.status()
        self.assertTrue(status["model"]["pending_apply"])

    def test_open_budget_does_not_reset_active_run(self):
        self.guard()
        with patch.object(self.service, "guard_status", return_value={"armed": True, "run": {"status": "open"}}), patch.object(self.service, "command") as command:
            result = self.service.open_budget()
        command.assert_not_called()
        self.assertTrue(result["reused"])

    def test_open_but_disarmed_budget_is_actually_armed(self):
        self.guard()
        state = {"armed": False, "run": {"status": "open", "usage": {"concurrency_used": 0}}}
        with patch.object(self.service, "guard_status", return_value=state), patch.object(self.service, "http", return_value={"armed": True}) as http:
            result = self.service.open_budget()
        self.assertTrue(result["armed"])
        http.assert_called_once()
        self.assertTrue(http.call_args.args[0].endswith("/admin/arm"))

    def test_active_queue_blocks_model_change(self):
        self.guard()
        status = {"run": {"status": "closed", "usage": {"concurrency_used": 0}}}
        with patch.object(self.service, "guard_status", return_value=status), patch.object(self.service, "running", return_value=True), patch.object(self.service, "command", return_value="1"):
            with self.assertRaises(module.Failure) as error:
                self.service.save_model({**self.model, "apply": True})
        self.assertEqual(error.exception.code, "active_investigations")
        self.assertEqual(json.loads(self.service.guard_file.read_text())["model"], "old")

    def test_real_probe_is_one_small_request_without_response_content_leak(self):
        with patch.object(self.service, "http", return_value={"choices": [{"message": {"content": "private provider content"}}]}) as request:
            result = self.service.test_model(self.model)
        self.assertTrue(result["ok"])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[2]["max_tokens"], 32)
        self.assertNotIn("private provider", json.dumps(result))

    def test_model_error_does_not_leak_credentials(self):
        with patch.object(self.service, "http", side_effect=RuntimeError(self.model["api_key"])):
            with self.assertRaises(module.Failure) as error:
                self.service.test_model(self.model)
        self.assertNotIn(self.model["api_key"], error.exception.message)

    def test_changed_provider_never_receives_saved_key(self):
        self.guard()
        with patch.object(self.service, "http") as http:
            with self.assertRaises(module.Failure) as error:
                self.service.test_model({"base_url": "https://other.example/v1", "model": "other"})
        self.assertEqual(error.exception.code, "new_endpoint_requires_key")
        http.assert_not_called()
        model = self.service.model_input({"base_url": "https://old.example/v1/", "model": "new-name"})
        self.assertEqual(model["api_key"], "old-private")

    def test_http_provider_is_rejected_before_probe(self):
        with patch.object(self.service, "http") as http:
            with self.assertRaises(module.Failure) as error:
                self.service.test_model({**self.model, "base_url": "http://localhost:8080/v1"})
        self.assertEqual(error.exception.code, "invalid_endpoint")
        http.assert_not_called()

    def test_ready_file_does_not_override_unhealthy_team(self):
        self.service.plan.mkdir()
        (self.service.plan / "runtime-ready.json").write_text("{}")
        self.service.state["phase"] = "ready"
        with patch.object(self.service, "running", return_value=True), patch.object(self.service, "team_ready", return_value=False), patch.object(self.service, "guard_status", side_effect=OSError):
            status = self.service.status()
        self.assertEqual(status["phase"], "idle")
        self.assertFalse(status["deployment"]["team_ready"])

    def test_updated_configuration_instantiates_real_guard_on_same_ledger(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        try:
            from cyberguard_investigation.model_guard import ModelGuard
        except ModuleNotFoundError:
            self.skipTest("Run this integration test in the Console image with FastAPI installed")
        cfg = {"run_id": "guard-initial", "model": "old", "evidence_hash": "a" * 64,
            "upstream_endpoint": "https://old.example/v1/chat/completions", "upstream_key": "u" * 40,
            "admin_token": "a" * 40, "roles": {"investigator": {"token": "i" * 40, "model_alias": "role-alias"}},
            "limits": {"max_requests": 3, "max_requests_per_role": 3, "max_input_tokens": 20000,
                       "max_output_tokens": 8000, "max_concurrency": 1}}
        module.private_write(self.service.guard_file, json.dumps(cfg))
        ledger = self.root / "ledger"
        original = ModelGuard(cfg, ledger)
        original.ledger.close_run(cfg["run_id"])
        made = []
        def launch():
            made.append(ModelGuard(json.loads(self.service.guard_file.read_text()), ledger))
        with patch.object(self.service, "ensure_idle"), patch.object(self.service, "command"), patch.object(self.service, "start_guard", side_effect=launch), patch.object(self.service, "wait_guard"):
            self.service.save_model({**self.model, "api_key": "provider-key", "apply": True})
        self.assertEqual(len(made), 1)
        self.assertNotEqual(made[0].run_id, original.run_id)
        self.assertEqual(original.ledger.get_run(original.run_id)["status"], "closed")
        self.assertEqual(made[0].roles, original.roles)

    def test_http_requires_server_token_and_rejects_unknown_commands(self):
        server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        server.service = self.service
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = "http://127.0.0.1:" + str(server.server_address[1])
        opener = build_opener(ProxyHandler({}))
        with self.assertRaises(HTTPError) as error:
            opener.open(url + "/v1/status")
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        request = Request(url + "/v1/execute", data=b'{"command":"rm -rf /"}', headers={"Authorization": "Bearer " + "x" * 48})
        with self.assertRaises(HTTPError) as error:
            opener.open(request)
        self.assertEqual(error.exception.code, 404)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
