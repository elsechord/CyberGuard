import atexit
import html
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "operations-console"))
WORK_DIR = ROOT / "tmp"
WORK_DIR.mkdir(exist_ok=True)
TEMP = tempfile.mkdtemp(prefix="console-test-", dir=str(WORK_DIR))
atexit.register(shutil.rmtree, TEMP, ignore_errors=True)
os.environ["CYBERGUARD_CONSOLE_DB"] = str(Path(TEMP) / "console.db")
os.environ["CYBERGUARD_COOKIE_SECURE"] = "false"
os.environ["CYBERGUARD_LOGIN_BACKOFF_BASE"] = "0"
os.environ["CYBERGUARD_GATEWAY_URL"] = ""
os.environ["CYBERGUARD_EXECUTOR_URL"] = ""
os.environ["CYBERGUARD_GUARD_URL"] = ""

from app import apikeys, auth, clients, db  # noqa: E402
from app.main import app  # noqa: E402

ADMIN = ("root-admin", "correct-horse-battery-9", "admin")


def setUpModule():
    # app.main may already have been imported under another test module's DB.
    # Initialize the current database explicitly instead of relying on import order.
    db.init_db()


def login(client: TestClient, username: str, password: str) -> None:
    page = client.get("/login")
    token = re.search(r'name="login_csrf" value="([^"]+)"', page.text).group(1)
    response = client.post("/login", data={
        "username": username, "password": password, "login_csrf": token},
        follow_redirects=False)
    assert response.status_code == 303, response.text


class OperationsConsoleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        if auth.user_count() == 0:
            auth.create_user(ADMIN[0], ADMIN[1], ADMIN[2])
            auth.finish_setup()
        login(self.client, ADMIN[0], ADMIN[1])

    # ------------------------------------------------ setup + login + lockout

    def test_setup_closes_after_first_admin(self) -> None:
        response = self.client.get("/setup", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))
        state = auth.setup_state()
        self.assertFalse(state["open"])
        self.assertIsNone(state["token"])

    def test_login_success_and_logout(self) -> None:
        fresh = TestClient(app)
        login(fresh, ADMIN[0], ADMIN[1])
        self.assertEqual(fresh.get("/").status_code, 200)
        page = fresh.get("/")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        response = fresh.post("/logout", data={"csrf_token": csrf},
                              follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        bounced = fresh.get("/", follow_redirects=False)
        self.assertEqual(bounced.status_code, 303)
        self.assertEqual(bounced.headers["location"], "/login")

    def test_login_failure_uses_unified_message(self) -> None:
        fresh = TestClient(app)
        page = fresh.get("/login")
        token = re.search(r'name="login_csrf" value="([^"]+)"', page.text).group(1)
        for username, password in ((ADMIN[0], "wrong-password-1"), ("ghost-user", "whatever-1")):
            response = fresh.post("/login", data={
                "username": username, "password": password, "login_csrf": token})
            self.assertEqual(response.status_code, 401)
            self.assertIn(auth.UNIFIED_LOGIN_MESSAGE, response.text)

    def test_login_locks_after_five_failures(self) -> None:
        auth.create_user("lock-target", "initial-password-1", "viewer")
        fresh = TestClient(app)
        page = fresh.get("/login")
        token = re.search(r'name="login_csrf" value="([^"]+)"', page.text).group(1)
        for _ in range(5):
            response = fresh.post("/login", data={
                "username": "lock-target", "password": "nope",
                "login_csrf": token})
            self.assertEqual(response.status_code, 401)
        locked = fresh.post("/login", data={
            "username": "lock-target", "password": "initial-password-1",
            "login_csrf": token})
        self.assertEqual(locked.status_code, 429)
        self.assertIn("锁定", locked.text)

    def test_password_hashing_format(self) -> None:
        stored = auth.hash_password("another-example-password")
        scheme, iterations, _, _ = stored.split("$")
        self.assertEqual(scheme, "pbkdf2_sha256")
        self.assertEqual(int(iterations), 600000)
        self.assertTrue(auth.verify_password("another-example-password", stored))
        self.assertFalse(auth.verify_password("wrong", stored))

    # ------------------------------------------------ sessions

    def test_session_rotation_on_login(self) -> None:
        first = TestClient(app)
        login(first, ADMIN[0], ADMIN[1])
        cookie_one = first.cookies.get("cgsession")
        second = TestClient(app)
        login(second, ADMIN[0], ADMIN[1])
        self.assertNotEqual(cookie_one, second.cookies.get("cgsession"))
        # Both sessions remain valid; ids are random 32-byte tokens.
        self.assertGreaterEqual(len(cookie_one), 40)

    def test_session_only_hash_is_persisted(self) -> None:
        from app import db
        rows = db.connection().execute("SELECT sid_hash FROM session").fetchall()
        import hashlib
        sid = TestClient(app)
        login(sid, ADMIN[0], ADMIN[1])
        raw = sid.cookies.get("cgsession")
        stored = db.connection().execute("SELECT sid_hash FROM session").fetchall()
        digests = {row["sid_hash"] for row in stored}
        self.assertIn(hashlib.sha256(raw.encode()).hexdigest(), digests)
        for row in stored:
            self.assertNotEqual(row["sid_hash"], raw)
        self.assertGreater(len(stored), len(rows))

    def test_privilege_change_revokes_sessions(self) -> None:
        auth.create_user("promote-me", "start-password-123", "viewer")
        session = TestClient(app)
        login(session, "promote-me", "start-password-123")
        self.assertEqual(session.get("/").status_code, 200)
        target = auth.get_user("promote-me")
        auth.set_user_role(target["id"], "analyst")
        bounced = session.get("/", follow_redirects=False)
        self.assertEqual(bounced.status_code, 303)
        self.assertEqual(bounced.headers["location"], "/login")

    # ------------------------------------------------ RBAC matrix

    def create_role_user(self, role: str) -> TestClient:
        username = f"matrix-{role}-{id(self)}"
        auth.create_user(username, "matrix-password-1", role)
        client = TestClient(app)
        login(client, username, "matrix-password-1")
        return client

    def test_rbac_matrix_pages(self) -> None:
        viewer = self.create_role_user("viewer")
        analyst = self.create_role_user("analyst")
        admin = TestClient(app)
        login(admin, ADMIN[0], ADMIN[1])
        self.assertEqual(viewer.get("/incidents").status_code, 200)
        self.assertEqual(viewer.get("/audit").status_code, 403)
        self.assertEqual(viewer.get("/settings/members").status_code, 403)
        self.assertEqual(analyst.get("/approvals").status_code, 200)
        self.assertEqual(admin.get("/audit").status_code, 200)
        self.assertEqual(admin.get("/settings/keys").status_code, 200)

    def test_rbac_matrix_workflow_forms(self) -> None:
        viewer = self.create_role_user("viewer")
        analyst = self.create_role_user("analyst")
        # Analyst may comment (CSRF layer rejects a bad token); viewer is
        # denied by RBAC before any upstream call happens.
        self.assertEqual(viewer.post(
            "/incidents/CG-1/comments", data={"csrf_token": "x", "body": "hi"},
        ).status_code, 403)
        self.assertEqual(analyst.post(
            "/incidents/CG-1/comments", data={"csrf_token": "missing", "body": "hi"},
        ).status_code, 403)
        self.assertEqual(viewer.post(
            "/approvals/ACT-1/decision",
            data={"action": "deny", "classification": "undetermined",
                  "comment": "not enough"}, follow_redirects=False).status_code, 403)

    def test_rbac_matrix_api(self) -> None:
        viewer = self.create_role_user("viewer")
        approver = self.create_role_user("approver")
        self.assertEqual(viewer.get("/api/v1/audit-events").status_code, 403)
        self.assertEqual(viewer.get("/api/v1/keys").status_code, 403)
        # decisions require decisions:write (approver role has it)
        with patch.object(clients, "executor_approve",
                          return_value={"action_id": "ACT-9", "status": "approved"}):
            response = viewer.post("/api/v1/proposals/ACT-9/decision", json={
                "action": "approve", "classification": "undetermined",
                "comment": "viewer cannot approve"}, headers=api_headers())
            self.assertEqual(response.status_code, 403)
            response = approver.post("/api/v1/proposals/ACT-9/decision", json={
                "action": "approve", "classification": "approved_with_caution",
                "comment": "evidence is consistent"}, headers=api_headers())
            self.assertEqual(response.status_code, 200)

    # ------------------------------------------------ CSRF

    def test_csrf_required_for_session_forms(self) -> None:
        response = self.client.post("/incidents/CG-1/comments",
                                    data={"body": "no token"})
        self.assertEqual(response.status_code, 403)

    def test_csrf_required_for_session_json_api(self) -> None:
        response = self.client.post("/api/v1/proposals/ACT-1/decision", json={
            "action": "deny", "classification": "undetermined", "comment": "x123"})
        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertEqual(payload["error"]["type"], "permission_error")
        # Correct Origin + X-Requested-With passes the CSRF layer (RBAC may still 403).
        response = self.client.post("/api/v1/proposals/ACT-1/decision", json={
            "action": "deny", "classification": "undetermined", "comment": "x123"},
            headers={"Origin": "http://testserver", "X-Requested-With": "fetch"})
        self.assertNotEqual(response.status_code, 403)

    def test_cross_origin_json_rejected(self) -> None:
        response = self.client.post("/api/v1/proposals/ACT-1/decision", json={
            "action": "deny", "classification": "undetermined", "comment": "x123"},
            headers={"Origin": "https://evil.example", "X-Requested-With": "fetch"})
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------ security headers

    def test_security_headers_and_csp(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.headers["content-security-policy"],
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
                         "form-action 'self'; frame-ancestors 'none'; base-uri 'self'")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_public_demo_account_has_full_access_and_is_shown_only_when_enabled(self) -> None:
        username, password = "goai-demo-test", "test-public-password-2026"
        anonymous = TestClient(app)
        self.assertNotIn("公开演示 · 完整体验", anonymous.get("/login").text)
        with patch.dict(os.environ, {
            "CYBERGUARD_PUBLIC_DEMO_USERNAME": username,
            "CYBERGUARD_PUBLIC_DEMO_PASSWORD": password,
        }):
            auth.ensure_public_demo_admin()
            user = auth.get_user(username)
            self.assertEqual(user["role"], "admin")
            page = anonymous.get("/login")
            self.assertIn(username, page.text)
            self.assertIn(password, page.text)
            login(anonymous, username, password)
            self.assertEqual(anonymous.get("/").status_code, 200)
            self.assertIn("investigations:write", auth.ROLE_SCOPE_GRANTS["admin"])
            self.assertIn("decisions:write", auth.ROLE_SCOPE_GRANTS["admin"])

    def test_active_investigation_visible_across_workbench(self) -> None:
        page = self.client.get("/investigations")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        key = re.search(r'name="idempotency_key" value="([^"]+)"', page.text).group(1)
        title = "页面进度可见性测试"
        created = self.client.post("/investigations/new", data={
            "csrf_token": csrf, "idempotency_key": key, "title": title,
            "objective": "核对材料", "domain": "security", "source_type": "other",
            "name": "测试记录", "content": "A single synthetic event."},
            follow_redirects=False)
        self.assertEqual(created.status_code, 303)
        detail_url = created.headers["location"]
        for path in ("/", "/incidents", "/investigations", "/investigations/active"):
            self.assertIn(title, self.client.get(path).text)
        self.assertIn(f'hx-get="{detail_url}"', self.client.get(detail_url).text)
        job_id = detail_url.rsplit("/", 1)[-1]
        with db.tx() as conn:
            row = conn.execute("SELECT payload FROM investigation_job WHERE id=?", (job_id,)).fetchone()
            payload = json.loads(row["payload"])
            payload["runtime"].update(project_id="native-test", workflow={
                "status": "active", "nodes": [{"id": "task-1", "name": "核对证据",
                    "assignee": "investigator", "status": "in-progress"}]})
            conn.execute("UPDATE investigation_job SET payload=? WHERE id=?",
                         (json.dumps(payload, ensure_ascii=False), job_id))
        detail = self.client.get(detail_url).text
        self.assertIn("协作现场", detail)
        self.assertIn("核对证据", detail)
        self.assertIn("取证 Agent", detail)

        # A failed investigation remains visible even though it is not a
        # security event from the gateway.
        with db.tx() as conn:
            payload["status"] = "failed"
            payload["stage"] = "native_connection"
            conn.execute("UPDATE investigation_job SET status=?,payload=? WHERE id=?",
                         ("failed", json.dumps(payload, ensure_ascii=False), job_id))
        for path in ("/", "/incidents"):
            self.assertIn("需要处理的调查", self.client.get(path).text)
            self.assertIn(title, self.client.get(path).text)
        with db.tx() as conn:
            payload["status"] = "completed"
            payload["stage"] = "complete"
            conn.execute("UPDATE investigation_job SET status=?,payload=? WHERE id=?",
                         ("completed", json.dumps(payload, ensure_ascii=False), job_id))
        self.assertIn("最近完成的调查", self.client.get("/").text)

    def test_managed_studio_shows_live_status_instead_of_host_wizard(self) -> None:
        with patch.dict(os.environ, {"CYBERGUARD_MODELSCOPE_EMBED": "1"}):
            page = self.client.get("/settings/onboarding")
            self.assertEqual(page.status_code, 200)
            self.assertIn("运行状态", page.text)
            self.assertNotIn("尚未连接宿主机部署服务", page.text)
            status = self.client.get("/settings/onboarding/status")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["data"]["mode"], "modelscope")
            self.assertEqual(self.client.post("/settings/onboarding/initialize").status_code, 409)

    def test_unauthorized_page_redirects_and_api_keeps_401(self) -> None:
        client = TestClient(app)
        bounced = client.get("/", follow_redirects=False)
        self.assertEqual(bounced.status_code, 303)
        self.assertEqual(bounced.headers["location"], "/login")
        api = client.get("/api/v1/incidents")
        self.assertEqual(api.status_code, 401)
        self.assertEqual(api.headers["www-authenticate"], "Bearer")

    # ------------------------------------------------ API keys

    def test_api_key_lifecycle(self) -> None:
        key_id, secret, meta = apikeys.create_key(
            name="ci", scopes=["incidents:read"], created_by=ADMIN[0])
        self.assertTrue(secret.startswith("cg_live_"))
        self.assertEqual(meta["prefix"], secret[:14])
        response = TestClient(app).get(
            "/api/v1/incidents",
            headers={"Authorization": f"Bearer {secret}"})
        # incidents:read grants the scope; the unconfigured gateway yields 503.
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["type"], "api_error")
        apikeys.revoke_key(key_id, ADMIN[0])
        revoked = TestClient(app).get(
            "/api/v1/incidents",
            headers={"Authorization": f"Bearer {secret}"})
        self.assertEqual(revoked.status_code, 401)
        self.assertEqual(revoked.json()["error"]["type"], "authentication_error")

    def test_api_key_scope_enforcement(self) -> None:
        _, secret, _ = apikeys.create_key(name="ro", scopes=["incidents:read"],
                                          created_by=ADMIN[0])
        response = TestClient(app).get(
            "/api/v1/audit-events",
            headers={"Authorization": f"Bearer {secret}"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["type"], "permission_error")
        self.assertEqual(response.json()["error"]["code"], "missing_scope")

    def test_api_key_last_used_touch(self) -> None:
        from app import db
        key_id, secret, _ = apikeys.create_key(name="touch",
                                               scopes=["usage:read"],
                                               created_by=ADMIN[0])
        TestClient(app).get("/api/v1/usage/summary",
                            headers={"Authorization": f"Bearer {secret}"})
        row = db.connection().execute("SELECT last_used_at FROM api_key WHERE id = ?",
                                      (key_id,)).fetchone()
        self.assertIsNotNone(row["last_used_at"])

    def test_admin_scope_implies_all(self) -> None:
        _, secret, _ = apikeys.create_key(name="root", scopes=["admin"],
                                          created_by=ADMIN[0])
        response = TestClient(app).get(
            "/api/v1/keys", headers={"Authorization": f"Bearer {secret}"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("data", response.json())

    # ------------------------------------------------ envelope + pagination

    def test_incident_envelope_pagination(self) -> None:
        incidents = [{"incident_id": f"CG-{index:03d}", "status": "investigating",
                      "evidence_count": index} for index in range(1, 26)]
        with patch.object(clients, "gateway_incidents", return_value=incidents):
            page_one = self.client.get("/api/v1/incidents?limit=10",
                                       headers=api_headers())
            body = page_one.json()
            self.assertEqual(page_one.status_code, 200)
            self.assertEqual(len(body["data"]), 10)
            self.assertTrue(body["has_more"])
            self.assertEqual(body["next_cursor"], "CG-010")
            page_two = self.client.get(
                "/api/v1/incidents?limit=10&cursor=CG-010", headers=api_headers())
            body_two = page_two.json()
            self.assertEqual(body_two["data"][0]["incident_id"], "CG-011")
            self.assertEqual(body_two["next_cursor"], "CG-020")
            last = self.client.get("/api/v1/incidents?limit=10&cursor=CG-020",
                                   headers=api_headers()).json()
            self.assertFalse(last["has_more"])
            self.assertIsNone(last["next_cursor"])

    def test_limit_bounds(self) -> None:
        with patch.object(clients, "gateway_incidents", return_value=[]):
            response = self.client.get("/api/v1/incidents?limit=0",
                                       headers=api_headers())
            self.assertEqual(response.status_code, 400)
            response = self.client.get("/api/v1/incidents?limit=101",
                                       headers=api_headers())
            self.assertEqual(response.json()["data"], [])

    def test_audit_events_envelope(self) -> None:
        response = self.client.get("/api/v1/audit-events?limit=5",
                                   headers=api_headers())
        body = response.json()
        self.assertLessEqual(len(body["data"]), 5)
        self.assertIn("event", body["data"][0])
        cursor = body["next_cursor"]
        if cursor:
            nxt = self.client.get(f"/api/v1/audit-events?limit=5&cursor={cursor}",
                                  headers=api_headers()).json()
            self.assertEqual(nxt["data"][0]["id"], int(cursor) - 1)

    def test_error_envelope_validation(self) -> None:
        response = self.client.post(
            "/api/v1/proposals/ACT-1/decision",
            json={"action": "approve", "classification": "bogus_class",
                  "comment": "invalid classification value"},
            headers=api_headers())
        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertEqual(payload["error"]["type"], "invalid_request_error")
        self.assertEqual(payload["error"]["code"], "invalid_classification")
        # Missing classification (or body) surfaces the shared envelope too.
        response = self.client.post("/api/v1/proposals/ACT-1/decision",
                                    json={"action": "deny", "comment": "x123"},
                                    headers=api_headers())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["type"], "invalid_request_error")
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        response = self.client.post("/api/v1/proposals/ACT-1/decision",
                                    json={"action": "sideways"},
                                    headers=api_headers())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["type"], "invalid_request_error")

    # ------------------------------------------------ idempotency

    def test_idempotency_replay_returns_original(self) -> None:
        approve_result = {"action_id": "ACT-42", "status": "approved"}
        with patch.object(clients, "executor_approve",
                          return_value=approve_result) as mocked:
            headers = api_headers({"Idempotency-Key": "key-replay-1"})
            first = self.client.post("/api/v1/proposals/ACT-42/decision", json={
                "action": "approve", "classification": "approved_true_positive",
                "comment": "confirmed by independent evidence"}, headers=headers)
            second = self.client.post("/api/v1/proposals/ACT-42/decision", json={
                "action": "approve", "classification": "approved_true_positive",
                "comment": "confirmed by independent evidence"}, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(second.headers.get("idempotent-replay"), "true")
        self.assertIsNone(first.headers.get("idempotent-replay"))
        self.assertEqual(mocked.call_count, 1)

    def test_idempotency_conflict_on_mismatch(self) -> None:
        headers = api_headers({"Idempotency-Key": "key-conflict-1"})
        with patch.object(clients, "executor_approve", return_value={"ok": True}):
            first = self.client.post("/api/v1/proposals/ACT-43/decision", json={
                "action": "approve", "classification": "approved_true_positive",
                "comment": "first flavour of parameters"}, headers=headers)
            conflict = self.client.post("/api/v1/proposals/ACT-43/decision", json={
                "action": "deny", "classification": "denied_false_positive_logic",
                "comment": "different parameters entirely"}, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["type"], "idempotency_error")

    def test_idempotency_rejects_long_keys(self) -> None:
        headers = api_headers({"Idempotency-Key": "x" * 256})
        response = self.client.post("/api/v1/proposals/ACT-44/decision", json={
            "action": "deny", "classification": "undetermined",
            "comment": "long key test"}, headers=headers)
        self.assertEqual(response.status_code, 422)

    # ------------------------------------------------ proposals + decisions

    def test_proposal_listing_from_gateway(self) -> None:
        incidents = [{"incident_id": "CG-777", "status": "awaiting_approval"}]
        detail = {"summary": {"status": "awaiting_approval"}, "actions": [
            {"action_id": "ACT-P1", "status": "pending_approval", "action": "isolate_endpoint"},
            {"action_id": "ACT-P2", "status": "executed", "action": "block_ioc"},
        ]}
        with patch.object(clients, "gateway_incidents", return_value=incidents), \
             patch.object(clients, "gateway_incident", return_value=detail):
            response = self.client.get("/api/v1/proposals", headers=api_headers())
        body = response.json()
        self.assertEqual([item["action_id"] for item in body["data"]], ["ACT-P1"])
        self.assertFalse(body["has_more"])

    def test_executor_incident_resolution_from_action_events(self) -> None:
        record = {"action_id": "ACT-9", "events": [
            {"action_id": "ACT-9", "incident_id": "CG-900", "status": "pending_approval"},
            {"action_id": "ACT-9", "incident_id": "CG-900", "status": "approved"},
        ]}
        with patch.object(clients, "executor_action", return_value=record):
            self.assertEqual(clients.executor_incident_for_action("ACT-9"), "CG-900")
        with patch.object(clients, "executor_action", return_value={"events": []}):
            self.assertIsNone(clients.executor_incident_for_action("ACT-9"))

    def test_proposal_listing_dedupes_action_audit_history(self) -> None:
        # The gateway action audit is append-ordered: an approved record for the
        # same action_id supersedes the earlier pending_approval record.
        incidents = [{"incident_id": "CG-778", "status": "awaiting_approval"}]
        detail = {"summary": {"status": "awaiting_approval"}, "actions": [
            {"action_id": "ACT-P9", "status": "pending_approval", "action": "disable_account"},
            {"action_id": "ACT-P9", "status": "approved", "action": "disable_account"},
        ]}
        with patch.object(clients, "gateway_incidents", return_value=incidents), \
             patch.object(clients, "gateway_incident", return_value=detail):
            response = self.client.get("/api/v1/proposals", headers=api_headers())
        self.assertEqual(response.json()["data"], [])

    def test_decision_approve_advances_gateway_workflow(self) -> None:
        with patch.object(clients, "executor_approve",
                          return_value={"incident_id": "CG-779"}), \
             patch.object(clients, "executor_incident_for_action",
                          return_value="CG-779"), \
             patch.object(clients, "advance_after_decision",
                          return_value="approved") as advanced:
            response = self.client.post("/api/v1/proposals/ACT-77/decision", json={
                "action": "approve", "classification": "approved_true_positive",
                "comment": "verified against evidence chain"}, headers=api_headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["workflow"], "approved")
        advanced.assert_called_once()
        call_args = advanced.call_args.args
        self.assertEqual(call_args[0], "CG-779")
        self.assertEqual(call_args[1], "approve")
        self.assertIn("approved_true_positive", call_args[3])
        events = self.client.get("/api/v1/audit-events?event=decision",
                                 headers=api_headers()).json()
        self.assertEqual(events["data"][0]["target"], "ACT-77")

    def test_decision_survives_gateway_outage(self) -> None:
        # advance_after_decision raising must not lose the recorded decision.
        with patch.object(clients, "executor_approve",
                          return_value={"incident_id": "CG-780"}), \
             patch.object(clients, "executor_incident_for_action",
                          return_value="CG-780"), \
             patch.object(clients, "advance_after_decision",
                          side_effect=clients.UpstreamError("gateway down")):
            response = self.client.post("/api/v1/proposals/ACT-81/decision", json={
                "action": "approve", "classification": "approved_with_caution",
                "comment": "decision recorded even if gateway is offline"},
                headers=api_headers())
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["data"]["workflow"])
        events = self.client.get("/api/v1/audit-events?event=decision",
                                 headers=api_headers()).json()
        self.assertEqual(events["data"][0]["result"], "approve")

    def test_decision_deny_without_executor_call(self) -> None:
        with patch.object(clients, "executor_approve") as mocked:
            response = self.client.post("/api/v1/proposals/ACT-55/decision", json={
                "action": "deny", "classification": "denied_false_positive_data",
                "comment": "alert fired on synthetic test data"}, headers=api_headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["decision"], "deny")
        mocked.assert_not_called()
        events = self.client.get("/api/v1/audit-events?event=decision",
                                 headers=api_headers()).json()
        self.assertEqual(events["data"][0]["reason"], "denied_false_positive_data")

    # ------------------------------------------------ upstream behaviour

    def test_upstream_unavailable_maps_to_502(self) -> None:
        with patch.object(clients, "gateway_incidents",
                          side_effect=clients.UpstreamError("upstream unavailable")):
            response = self.client.get("/api/v1/incidents", headers=api_headers())
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()["error"]["type"], "api_error")
            self.assertIn("upstream", response.json()["error"]["message"])
        # A raw transport failure inside _fetch is converted to UpstreamError:
        # port 1 on loopback refuses connections immediately.
        with self.assertRaises(clients.UpstreamError):
            clients._fetch("http://127.0.0.1:1", "/health")

    def test_upstream_error_passthrough(self) -> None:
        conflict = clients.UpstreamError("upstream request failed", status=409,
                                         detail={"detail": "invalid workflow transition"})
        with patch.object(clients, "gateway_transition", side_effect=conflict):
            response = self.client.post("/api/v1/incidents/CG-900/workflow", json={
                "state": "completed", "message": "shortcut"},
                headers=api_headers({"Idempotency-Key": "wf-1"}))
        self.assertEqual(response.status_code, 409)
        self.assertIn("invalid workflow transition", response.json()["error"]["message"])

    def test_usage_summary_degrades(self) -> None:
        response = self.client.get("/api/v1/usage/summary", headers=api_headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], {"available": False})
        with patch.object(clients, "guard_status",
                          return_value={"available": True, "armed": True,
                                        "run": {"run_id": "RUN-1", "status": "open",
                                                "usage": {"requests": 3}}}):
            body = self.client.get("/api/v1/usage/summary",
                                   headers=api_headers()).json()["data"]
        self.assertTrue(body["available"])
        self.assertEqual(body["run_id"], "RUN-1")
        self.assertEqual(body["consumption"]["requests"], 3)

    # ------------------------------------------------ pages

    def test_pages_render(self) -> None:
        for path in ("/", "/incidents", "/approvals", "/ledger"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
        # Unreachable gateway renders the unavailable card, a 404 passes through.
        self.assertIn("不可用", self.client.get("/incidents/CG-404").text)
        with patch.object(clients, "gateway_incident",
                          side_effect=clients.UpstreamError("not found", status=404)):
            self.assertEqual(self.client.get("/incidents/CG-404").status_code, 404)
        self.assertEqual(self.client.get("/audit/export.csv").status_code, 200)
        self.assertIn(ADMIN[0], self.client.get("/audit").text)

    def test_audit_export_contains_login_events(self) -> None:
        export = self.client.get("/audit/export.csv").text
        self.assertIn("login", export)
        self.assertIn(ADMIN[0], export)

    def test_members_page_requires_admin(self) -> None:
        viewer = self.create_role_user("viewer")
        self.assertEqual(viewer.get("/settings/members").status_code, 403)
        self.assertEqual(self.client.get("/settings/members").status_code, 200)

    def test_keys_page_shows_secret_once(self) -> None:
        page = self.client.get("/settings/keys")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        created = self.client.post("/settings/keys", data={
            "csrf_token": csrf, "name": "ui-key", "scopes": "incidents:read",
            "expires_in_days": ""}, follow_redirects=False)
        self.assertEqual(created.status_code, 200)
        match = re.search(r"id=\"secret-value\">(cg_live_[A-Za-z0-9_\-]+)<", created.text)
        self.assertIsNotNone(match)
        # The plaintext never appears on subsequent list renders.
        listing = self.client.get("/settings/keys")
        self.assertNotIn(match.group(1), listing.text)


class AgentConnectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"CYBERGUARD_CONSOLE_ORIGIN": "https://console.example.com"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.upstream = patch.object(clients, "gateway_incidents", return_value=[{"incident_id": "CG-real-1"}])
        self.gateway = self.upstream.start()
        self.addCleanup(self.upstream.stop)
        if auth.user_count() == 0:
            auth.create_user(*ADMIN)
            auth.finish_setup()
        self.client = TestClient(app)
        login(self.client, ADMIN[0], ADMIN[1])
        self.csrf = re.search(r'name="csrf_token" value="([^"]+)"', self.client.get("/connect").text).group(1)

    def post(self, endpoint="prompt", **values):
        return self.client.post("/connect/" + endpoint, data={"csrf_token": self.csrf, "purpose": "read", **values})

    def prompt(self, response):
        match = re.search(r'<textarea id="connection-prompt"[^>]*>(.*?)</textarea>', response.text, re.S)
        self.assertIsNotNone(match, response.text)
        return html.unescape(match.group(1))

    def test_connect_requires_session_and_csrf(self):
        fresh = TestClient(app)
        for path in ("/connect", "/connect/prompt", "/connect/key"):
            response = (fresh.get(path, follow_redirects=False) if path == "/connect"
                        else fresh.post(path, follow_redirects=False))
            self.assertIn(response.status_code, (303, 401))
        with patch.object(apikeys, "create_key") as create:
            for endpoint in ("prompt", "key"):
                self.assertEqual(self.client.post("/connect/" + endpoint, data={"csrf_token": "wrong"}).status_code, 403)
            create.assert_not_called()

    def test_viewer_can_prepare_prompt_but_cannot_issue_key(self):
        auth.create_user("connect-viewer", "connect-viewer-password", "viewer")
        viewer = TestClient(app)
        login(viewer, "connect-viewer", "connect-viewer-password")
        page = viewer.get("/connect")
        self.assertEqual(page.status_code, 200)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        self.assertEqual(viewer.post("/connect/prompt", data={"csrf_token": csrf}).status_code, 200)
        with patch.object(apikeys, "create_key") as create:
            self.assertEqual(viewer.post("/connect/key", data={"csrf_token": csrf}).status_code, 403)
            create.assert_not_called()

    def test_bearer_key_cannot_replace_browser_session(self):
        _, raw, _ = apikeys.create_key(name="connect-admin-api", scopes=["admin"], created_by=ADMIN[0])
        fresh = TestClient(app)
        for path in ("/connect/prompt", "/connect/key"):
            response = fresh.post(path, headers={"Authorization": "Bearer " + raw}, follow_redirects=False)
            self.assertIn(response.status_code, (303, 401))

    def test_get_and_prompt_do_not_issue_credentials(self):
        with patch.object(apikeys, "create_key") as create:
            page = self.client.get("/connect?issue_key=true", headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example"})
            self.assertIn("https://console.example.com", self.prompt(page))
            self.assertNotIn("evil.example", self.prompt(page))
            self.assertEqual(self.post().status_code, 200)
            create.assert_not_called()

    def test_key_scope_expiry_and_secret_separation(self):
        response = self.post("key", scopes="approvals:write,admin", expires_in_days="0", expires_at="2099-01-01", incident_id="CG-real-1")
        self.assertEqual(response.status_code, 200)
        raw = re.search(r'id="connection-secret">(cg_live_[A-Za-z0-9_-]+)<', response.text).group(1)
        row = apikeys.verify_key(raw)
        self.assertEqual(json.loads(row["scopes"]), ["incidents:read"])
        remaining = (datetime.fromisoformat(row["expires_at"]) - datetime.now(UTC)).total_seconds()
        self.assertGreater(remaining, 29 * 86400)
        self.assertLessEqual(remaining, 30 * 86400)
        self.assertNotIn(raw, self.prompt(response))
        self.assertNotIn(raw, self.client.get("/connect").text)
        self.assertNotIn(raw, self.client.get("/settings/keys").text)
        self.assertEqual(row["key_hash"], apikeys.key_hash(raw))

    def test_prompt_ignores_submitted_secret_origin_and_scope(self):
        response = self.post(api_key="cg_live_do_not_echo", origin="https://evil.example", console_url="https://evil.example", scopes="admin", key_file="C:\\Users\\me\\key", incident_id="CG-real-1")
        prompt = self.prompt(response)
        self.assertIn("https://console.example.com", prompt)
        self.assertIn("CG-real-1", prompt)
        self.assertNotIn("evil.example", prompt)
        self.assertNotIn("cg_live_do_not_echo", response.text)

    def test_unconfigured_host_is_not_inferred(self):
        with patch.dict(os.environ, {"CYBERGUARD_CONSOLE_ORIGIN": ""}):
            response = self.client.get("/connect", headers={"Host": "evil.example", "X-Forwarded-Host": "console.example.com", "X-Forwarded-Proto": "https"})
        self.assertNotIn('id="connection-prompt"', response.text)
        self.assertIn("CYBERGUARD_CONSOLE_ORIGIN", response.text)
        self.assertNotIn("https://evil.example", response.text)

    def test_invalid_configured_origins_do_not_generate_prompt_or_key(self):
        origins = ("https://..", "https://-", "https://a..example", "http://remote.example", "https://user:password@example.com", "https://example.com/api", "https://example.com?token=secret", "https://example.com#frag", "https://example.com:99999", "https://example.com\\evil", "https://example.com\n")
        with patch.object(apikeys, "create_key") as create:
            for origin in origins:
                with self.subTest(origin=origin), patch.dict(os.environ, {"CYBERGUARD_CONSOLE_ORIGIN": origin}):
                    response = self.post("key")
                    self.assertEqual(response.status_code, 422)
                    self.assertNotIn('id="connection-prompt"', response.text)
            create.assert_not_called()

    def test_invalid_agent_incident_and_path_cannot_create_key(self):
        cases = ({"agent": "shell"}, {"incident_id": "CG-missing"}, {"incident_id": "../secrets"}, {"key_file": "relative/key"}, {"key_file": "cg_live_not_a_path"}, {"key_file": "/tmp/key\nprint-secret"}, {"key_file": "/" + "x" * 513})
        with patch.object(apikeys, "create_key") as create:
            for case in cases:
                with self.subTest(case=case):
                    self.assertEqual(self.post("key", **case).status_code, 422)
            create.assert_not_called()

    def test_empty_and_failed_upstream_are_distinct(self):
        self.gateway.return_value = []
        empty = self.client.get("/connect?purpose=read")
        self.assertIn("当前没有事件", empty.text)
        self.assertNotIn("证据服务当前不可用", empty.text)
        self.assertIn("本次只验证连接", self.prompt(empty))
        self.gateway.side_effect = clients.UpstreamError("upstream unavailable")
        failed = self.client.get("/connect?purpose=read")
        self.assertIn("证据服务当前不可用", failed.text)
        self.assertNotIn("当前没有事件", failed.text)
        self.assertIn("本次只验证连接", self.prompt(failed))
        self.assertEqual(self.post(incident_id="CG-real-1").status_code, 422)


def api_headers(extra: dict | None = None) -> dict:
    headers = {"Origin": "http://testserver", "X-Requested-With": "fetch"}
    if extra:
        headers.update(extra)
    return headers


class SetupFlowTest(unittest.TestCase):
    """First-boot setup on an isolated database, exercised end to end."""

    def test_setup_flow_opens_then_closes(self) -> None:
        original = os.environ["CYBERGUARD_CONSOLE_DB"]
        os.environ["CYBERGUARD_CONSOLE_DB"] = str(Path(TEMP) / "setup-flow.db")
        try:
            db.init_db()
            token = auth.ensure_setup_token()
            self.assertIsNotNone(token)
            client = TestClient(app)
            # Fresh instance: /login forwards to /setup while no user exists.
            self.assertTrue(client.get("/login", follow_redirects=False)
                            .headers["location"].startswith("/setup"))
            page = client.get("/setup")
            self.assertEqual(page.status_code, 200)
            self.assertNotIn(token, page.text)  # only the masked preview shows
            csrf = re.search(r'name="login_csrf" value="([^"]+)"', page.text).group(1)
            wrong = client.post("/setup", data={
                "login_csrf": csrf, "setup_token": "not-the-token",
                "username": "boot-admin", "password": "long-enough-password",
                "password_confirm": "long-enough-password"})
            self.assertEqual(wrong.status_code, 422)
            created = client.post("/setup", data={
                "login_csrf": csrf, "setup_token": token,
                "username": "boot-admin", "password": "long-enough-password",
                "password_confirm": "long-enough-password"},
                follow_redirects=False)
            self.assertEqual(created.status_code, 303)
            # Setup is permanently closed; the token is wiped.
            self.assertEqual(created.headers["location"], "/settings/onboarding")
            self.assertEqual(client.get("/settings/onboarding").status_code, 200)
            self.assertEqual(client.get("/setup", follow_redirects=False).status_code, 303)
            state = auth.setup_state()
            self.assertFalse(state["open"])
            self.assertIsNone(state["token"])
            client.cookies.clear()
            login(client, "boot-admin", "long-enough-password")
            self.assertEqual(client.get("/").status_code, 200)
        finally:
            os.environ["CYBERGUARD_CONSOLE_DB"] = original


if __name__ == "__main__":
    unittest.main()
