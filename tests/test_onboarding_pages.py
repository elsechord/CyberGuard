import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "operations-console"))
from app import auth, db, onboarding
# The app initializes its database during import, before unittest setUp runs.
# Keep that initialization isolated too, including on unprivileged CI runners.
with tempfile.TemporaryDirectory() as import_dir:
    with patch.dict(os.environ, {"CYBERGUARD_CONSOLE_DB": str(Path(import_dir) / "import.db")}):
        from app.main import app
        # Release the import-time SQLite handle before deleting its directory
        # (Windows does not allow unlinking an open database).
        db.connection().close()
        db._LOCAL.conn = None


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {"CYBERGUARD_CONSOLE_DB": str(Path(self.temp.name) / "test.db"),
            "CYBERGUARD_COOKIE_SECURE": "false", "CYBERGUARD_LOGIN_BACKOFF_BASE": "0",
            "CYBERGUARD_ONBOARDING_URL": "", "CYBERGUARD_ONBOARDING_SOCKET": "",
            "CYBERGUARD_ONBOARDING_TOKEN": "", "CYBERGUARD_ONBOARDING_TOKEN_FILE": ""})
        self.env.start(); db.init_db()
        auth.create_user("admin-wizard", "wizard-password-123", "admin"); auth.finish_setup()
        self.client = TestClient(app)
        self.login("admin-wizard")
        self.csrf = re.search(r'name="csrf_token" value="([^"]+)"', self.client.get("/settings/onboarding").text).group(1)

    def tearDown(self):
        self.client.close(); self.env.stop(); self.temp.cleanup()

    def login(self, username):
        page=self.client.get("/login")
        token=re.search(r'name="login_csrf" value="([^"]+)"',page.text).group(1)
        self.client.post("/login",data={"username":username,"password":"wizard-password-123","login_csrf":token},follow_redirects=False)

    def test_missing_bridge_is_visible_not_ready(self):
        self.assertIn("尚未连接宿主机部署服务", self.client.get("/settings/onboarding").text)
        self.assertEqual(self.client.get("/settings/onboarding/status").status_code,503)

    def test_session_and_admin_required(self):
        c=TestClient(app)
        self.assertEqual(c.get("/settings/onboarding/status",headers={"Authorization":"Bearer arbitrary"},follow_redirects=False).status_code,303)
        auth.create_user("viewer-wizard","wizard-password-123","viewer")
        self.client.cookies.clear();self.login("viewer-wizard")
        self.assertEqual(self.client.get("/settings/onboarding").status_code,403)

    def test_csrf_prevents_mutation(self):
        with patch.object(onboarding,"bridge") as call:
            r=self.client.post("/settings/onboarding/initialize",data={"csrf_token":"wrong"})
            self.assertEqual(r.status_code,403);call.assert_not_called()

    def test_save_forwards_secret_without_reflection(self):
        with patch.object(onboarding,"bridge",return_value={"saved":True,"api_key":"never-echo"}) as call:
            r=self.client.post("/settings/onboarding/save",data={"csrf_token":self.csrf,"base_url":"https://example.com/v1","model":"demo","api_key":"never-echo"})
            self.assertEqual(r.status_code,200);self.assertNotIn("never-echo",r.text)
            self.assertEqual(call.call_args.args[2]["api_key"],"never-echo")
            self.assertFalse(call.call_args.args[2]["apply"])

    def test_status_projects_secrets_and_error(self):
        with patch.object(onboarding,"bridge",return_value={"phase":"failed","error":"secret-provider-body","api_key":"secret","model":{"model":"demo","has_api_key":True,"pending_apply":True,"api_key":"secret"},"deployment":{"team_ready":False}}):
            r=self.client.get("/settings/onboarding/status")
            self.assertEqual(r.status_code,200);self.assertNotIn("secret-provider-body",r.text);self.assertNotIn('"api_key"',r.text)
            self.assertTrue(r.json()["data"]["model"]["pending_apply"])
            self.assertFalse(r.json()["data"]["deployment"]["team_ready"])
        with patch.object(onboarding,"bridge",return_value={"model":{"pending_apply":False},"deployment":{"team_ready":True}}):
            r=self.client.get("/settings/onboarding/status")
            self.assertFalse(r.json()["data"]["model"]["pending_apply"])
            self.assertTrue(r.json()["data"]["deployment"]["team_ready"])

    def test_initialize_is_async(self):
        with patch.object(onboarding,"bridge",return_value={"operation_id":"op-1","phase":"initializing"}) as call:
            r=self.client.post("/settings/onboarding/initialize",data={"csrf_token":self.csrf})
            self.assertEqual(r.status_code,202);self.assertEqual(call.call_args.args,("POST","initialize",{}))

    def test_url_credentials_are_rejected(self):
        with patch.object(onboarding,"bridge") as call:
            r=self.client.post("/settings/onboarding/test",data={"csrf_token":self.csrf,"base_url":"https://user:secret@example.com/v1","model":"demo"})
            self.assertEqual(r.status_code,422);self.assertNotIn("secret",r.text);call.assert_not_called()

    def test_apply_and_budget_are_explicit_actions(self):
        with patch.object(onboarding,"bridge",return_value={"saved":True,"applied":True}) as call:
            r=self.client.post("/settings/onboarding/apply",data={"csrf_token":self.csrf,"base_url":"https://example.com/v1","model":"demo"})
            self.assertEqual(r.status_code,200);self.assertTrue(call.call_args.args[2]["apply"])
        with patch.object(onboarding,"bridge",return_value={"armed":True,"run_id":"new"}) as call:
            r=self.client.post("/settings/onboarding/enable",data={"csrf_token":self.csrf})
            self.assertEqual(r.status_code,200);self.assertEqual(call.call_args.args,("POST","budget/open",{}))

    def test_malformed_url_is_validation_error(self):
        r=self.client.post("/settings/onboarding/test",data={"csrf_token":self.csrf,"base_url":"http://[bad","model":"demo"})
        self.assertEqual(r.status_code,422)

    def test_unix_socket_authentication(self):
        tokenfile=Path(self.temp.name)/"host-token";tokenfile.write_text("host-secret",encoding="utf-8")
        with patch.dict(os.environ,{"CYBERGUARD_ONBOARDING_SOCKET":"/run/cg/service.sock","CYBERGUARD_ONBOARDING_TOKEN_FILE":str(tokenfile)}), patch.object(onboarding,"UnixConnection") as connection:
            response=connection.return_value.getresponse.return_value;response.status=200;response.read.return_value=b'{"data":{"phase":"idle"}}'
            result=onboarding.bridge("GET","status")
            self.assertEqual(result["phase"],"idle")
            connection.assert_called_once_with("/run/cg/service.sock")
            self.assertEqual(connection.return_value.request.call_args.kwargs["headers"]["Authorization"],"Bearer host-secret")
            connection.return_value.close.assert_called_once()


if __name__ == "__main__": unittest.main()
