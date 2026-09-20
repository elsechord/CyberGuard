"""Administrator-only setup wizard; credentials stay on the server side."""
import json
import io
import http.client
import socket
from pathlib import Path
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .pages import page_session, form_of, check_csrf
from .render import render

router = APIRouter(include_in_schema=False)


def studio_mode():
    return os.getenv("CYBERGUARD_MODELSCOPE_EMBED", "").strip() == "1"


def studio_status():
    """Read the managed Studio services without the self-host deployment bridge."""
    from . import clients
    from .agentteams_native import config as native_config, controller
    from .agentteams_bridge import BridgeError as NativeError, _http

    guard = clients.guard_status()
    result = {"mode": "modelscope", "model": (guard.get("run") or {}).get("model", ""),
              "guard": bool(guard.get("available")), "armed": bool(guard.get("armed")),
              "controller": False, "matrix": False, "team": False, "workers": 0,
              "errors": []}
    try:
        cfg = native_config()
    except NativeError:
        result["errors"].append("AgentTeams 尚未配置。")
        return result
    try:
        team = controller(cfg, "GET", "/teams/" + cfg["TEAM_ID"])
        result["controller"] = result["team"] = True
        result["workers"] = len(team.get("workerMembers") or [])
    except NativeError as exc:
        result["errors"].append("Controller 或调查团队不可达（" + exc.code + "）。")
    try:
        account = _http(cfg, "GET", "/_matrix/client/v3/account/whoami", token=cfg["MATRIX_TOKEN"])
        result["matrix"] = bool(account.get("user_id"))
    except NativeError as exc:
        result["errors"].append("Matrix 通信不可达（" + exc.code + "）。")
    if not result["guard"]:
        result["errors"].append("模型预算服务不可达。")
    return result


class BridgeError(Exception):
    def __init__(self, message, status=503):
        self.message, self.status = message, status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def token():
    filename = os.getenv("CYBERGUARD_ONBOARDING_TOKEN_FILE", "")
    if filename:
        try:
            return Path(filename).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return os.getenv("CYBERGUARD_ONBOARDING_TOKEN", "").strip()


def configured():
    return bool((os.getenv("CYBERGUARD_ONBOARDING_SOCKET", "") or
                 os.getenv("CYBERGUARD_ONBOARDING_URL", "")) and token())


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=45)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def admin(request):
    principal = page_session(request)
    if principal.role != "admin":
        raise HTTPException(403, "只有管理员可以配置部署。")
    return principal


def bridge(method, path, payload=None):
    if not configured():
        raise BridgeError("尚未连接部署服务。请先在宿主机启动 CyberGuard 部署服务，并配置控制台连接。")
    origin = os.getenv("CYBERGUARD_ONBOARDING_URL", "").rstrip("/")
    headers = {"Authorization": "Bearer " + token(), "Content-Type": "application/json"}
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        socket_path = os.getenv("CYBERGUARD_ONBOARDING_SOCKET", "")
        if socket_path:
            conn = UnixConnection(socket_path)
            try:
                conn.request(method, "/v1/" + path, body=data, headers=headers)
                response = conn.getresponse()
                if response.status >= 300:
                    raise urllib.error.HTTPError("local-deployment-service", response.status, "request failed", {}, io.BytesIO(response.read(16 * 1024)))
                raw = response.read(128 * 1024 + 1)
            finally:
                conn.close()
            if len(raw) > 128 * 1024:
                raise ValueError("large response")
            result = json.loads(raw)
        else:
            req = urllib.request.Request(origin + "/v1/" + path, data=data, headers=headers, method=method)
            with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(req, timeout=45) as response:
                raw = response.read(128 * 1024 + 1)
                if len(raw) > 128 * 1024:
                    raise ValueError("large response")
                result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            error_code = json.loads(exc.read(16 * 1024)).get("error", {}).get("code", "")
        except (ValueError, AttributeError, OSError):
            error_code = ""
        messages = {
            "new_endpoint_requires_key": "更换模型服务地址后，请重新输入该服务的 API Key。",
            "invalid_model": "请填写服务地址、模型名和首次使用的 API Key。",
            "invalid_endpoint": "模型地址格式不正确，请填写不含凭据和查询参数的 HTTPS 地址。",
            "model_test_failed": "模型测试失败，请检查地址、API Key 和模型是否可用。",
            "redirect_rejected": "模型服务返回了重定向，请填写最终 API 地址。",
            "initializing": "初始化正在进行，请等待完成。",
            "initialization_required": "请先初始化调查服务。",
            "model_update_pending": "模型配置尚未应用，请先初始化或保存并应用配置。",
            "model_service_busy": "模型预算仍开放或有请求在途，请关闭预算并等待请求结束后再更新。",
            "active_investigations": "仍有调查任务在运行，请完成或取消后再更新部署。",
            "guard_unavailable": "暂时无法确认模型服务状态，请检查服务后重试。",
            "queue_unavailable": "暂时无法确认调查队列，未更改部署。",
        }
        message = messages.get(error_code) or {401: "部署服务身份验证失败，请检查服务端连接配置。",
                   409: "当前有运行中的任务或初始化操作，请等待完成后再试。",
                   422: "模型配置未通过检查，请确认地址、模型名和密钥。"}.get(exc.code,
                   "部署服务未完成请求，请检查配置或稍后重试。")
        raise BridgeError(message, 409 if exc.code == 409 else 502) from None
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
        raise BridgeError("无法连接部署服务，请确认服务正在运行。") from None
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        raise BridgeError("部署服务返回了无法识别的状态。", 502)
    return result["data"]


def public_status(value):
    model = value.get("model") or {}
    deployment = value.get("deployment") or {}
    budget = value.get("budget") or {}
    # Explicit projection prevents future host-side secrets entering browser responses.
    return {"budget": {"armed": bool(budget.get("armed")), "status": budget.get("status", "unavailable"),
                       "run_id": budget.get("run_id", ""),
                       "limits": {k: v for k, v in (budget.get("limits") or {}).items() if isinstance(v, (int, float))}},
            "phase": value.get("phase", "idle"), "step": value.get("step", ""),
            "error": "初始化未完成，请检查宿主机部署日志后重试。" if value.get("error") else "",
            "operation_id": value.get("operation_id", ""),
            "model": {k: model.get(k) for k in ("configured", "base_url", "model", "has_api_key", "pending_apply")},
            "deployment": {k: bool(deployment.get(k)) for k in ("prepared", "controller_running", "guard_running", "team_ready")}}


@router.get("/settings/onboarding")
def page(request: Request):
    principal = admin(request)
    if studio_mode():
        return render(request, "studio_status.html", principal=principal,
                      state=studio_status())
    return render(request, "onboarding.html", principal=principal, connected=configured())


@router.get("/settings/onboarding/status")
async def status(request: Request):
    admin(request)
    if studio_mode():
        return {"data": studio_status()}
    try:
        return {"data": public_status(await run_in_threadpool(bridge, "GET", "status"))}
    except BridgeError as exc:
        return JSONResponse({"error": {"message": exc.message}}, status_code=exc.status)


@router.post("/settings/onboarding/{action}")
async def action(request: Request, action: str):
    principal = admin(request)
    if studio_mode():
        return JSONResponse({"error": {"message": "此创空间由魔搭运行环境托管；模型与团队配置通过创空间设置更新。"}}, status_code=409)
    if action not in {"test", "save", "apply", "initialize", "enable"}:
        raise HTTPException(404)
    body = await request.body()
    if len(body) > 16 * 1024:
        raise HTTPException(413, "配置内容过长。")
    form = await form_of(request)
    check_csrf(principal, form)
    payload = {}
    if action in {"test", "save", "apply"}:
        base_url, model = form.get("base_url", "").strip(), form.get("model", "").strip()
        try:
            parsed = urlsplit(base_url)
        except ValueError:
            return JSONResponse({"error": {"message": "模型服务地址格式不正确。"}}, status_code=422)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or not model or len(model) > 200):
            return JSONResponse({"error": {"message": "请填写不含凭据或查询参数的 HTTPS 地址和模型名。"}}, status_code=422)
        payload = {"base_url": base_url, "model": model}
        if form.get("api_key", "").strip():
            payload["api_key"] = form["api_key"].strip()
        if action in {"save", "apply"}:
            payload["apply"] = action == "apply"
    try:
        data = await run_in_threadpool(bridge, "POST", {"initialize": "initialize", "enable": "budget/open", "apply": "model/save"}.get(action, "model/" + action), payload)
        allowed = {"test": ("ok", "model", "latency_ms"), "save": ("saved", "applied", "restart_required"),
                   "apply": ("saved", "applied", "restart_required"), "enable": ("armed", "reused", "run_id"),
                   "initialize": ("operation_id", "phase")}[action]
        return JSONResponse({"data": {k: data.get(k) for k in allowed}}, status_code=202 if action == "initialize" else 200)
    except BridgeError as exc:
        return JSONResponse({"error": {"message": exc.message}}, status_code=exc.status)
