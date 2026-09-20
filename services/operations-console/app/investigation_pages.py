"""Session-authenticated, CSRF-protected investigation intake and status pages."""
import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from . import jobs
from .errors import ApiError, invalid_request, permission_error
from .intake import MAX_SUBMISSION_BYTES
from .pages import page_session, form_of, check_csrf
from .render import render

router = APIRouter(include_in_schema=False)
DOMAINS = {"security": "安全调查", "finance": "财务材料审阅", "legal": "法律材料审阅", "general": "通用材料调查"}
SOURCES = {"agent": "Agent 提交", "firewall": "防火墙", "edr": "EDR", "honeypot": "蜜罐",
           "server_log": "服务器日志", "financial_record": "财务记录", "audit_report": "审计报告",
           "judicial_document": "司法文书", "other": "其他"}
STATUSES = {"queued": "排队中", "running": "处理中", "waiting_backend": "等待后端",
            "completed": "已完成", "failed": "失败", "canceled": "已取消"}
STAGES = {"accepted": "材料已接收", "budget": "等待模型预算", "investigator": "调查取证", "planner": "分析与建议",
          "native_dispatch": "交由团队处理", "native_tasks": "团队调查中", "native_attention": "需要关注", "native_connection": "连接团队",
          "verifier": "独立复核", "complete": "报告已完成", "integrity": "材料完整性检查",
          "validation": "结果校验"}
MESSAGES = {
    "Waiting for an available, armed model budget": "等待管理员开启本次模型调用预算。材料已保存，尚未发送给 Worker。",
    "Materials accepted; backend investigation pending.": "材料已保存，等待后端开始调查。",
    "Future stages canceled; a dispatched remote inference may still finish.": "已取消后续阶段；已发出的远程请求可能继续完成。",
    "Backend checkpoint persisted.": "本阶段进展已保存。",
    "Backend step unavailable; will retry safely": "后端暂时不可用，任务将稍后重试。",
    "Stored input integrity check failed": "保存的材料未通过完整性检查。",
    "Invalid backend state": "后端返回了无法识别的任务状态。",
    "Backend completion has no validated report": "后端尚未返回通过校验的报告。",
    "AgentTeams Worker did not return a validated report before the deadline": "Worker 未在时限内返回通过校验的报告。",
    "AgentTeams investigation exceeded its overall deadline": "调查已超过总处理时限。",
    "AgentTeams connection is not configured": "尚未配置 AgentTeams 连接，请联系管理员。",
    "AgentTeams is unavailable": "AgentTeams 暂时不可用。",
    "AgentTeams rejected the connection": "AgentTeams 拒绝了连接，请管理员检查凭据与权限。",
    "AgentTeams project or room no longer exists": "AgentTeams 项目或会话已不存在。请检查运行环境是否重启；此任务需要重新提交。",
    "AgentTeams runtime restarted; rebuilding the investigation": "AgentTeams 运行环境已重启，正在从原始材料恢复调查。",
    "Materials exceed the AgentTeams message size limit": "材料超过后端单次消息大小限制。",
    "Worker report failed evidence citation validation": "Worker 报告未通过材料引用校验。",
}


def stage_label(value):
    role, _, step = str(value).partition(".")
    if role in STAGES and step in {"prepare", "wait", "send"}:
        return STAGES[role] + " · " + {"prepare": "准备中", "wait": "等待结果", "send": "提交中"}[step]
    return STAGES.get(value, value)


def message_label(value):
    return MESSAGES.get(value, value)


async def _bounded_form(request):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_SUBMISSION_BYTES:
            raise invalid_request("提交内容超过 1 MiB，请减少材料后重试。", status=413)
        body.extend(chunk)
    request._body = bytes(body)
    return await form_of(request)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("JSON 包含重复字段。")
        value[key] = item
    return value


def _payload(form):
    if form.get("submission_json", "").strip():
        try:
            return json.loads(form["submission_json"], object_pairs_hook=_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("JSON 数值无效。")))
        except (ValueError, RecursionError) as exc:
            raise invalid_request("高级提交必须是有效 JSON，且不能包含重复字段。") from exc
    return {"title": form.get("title", ""), "objective": form.get("objective", ""),
            "domain": form.get("domain", "security"), "materials": [{
                "source_type": form.get("source_type", "other"), "name": form.get("name", ""),
                "content": form.get("content", ""), "media_type": "text/plain",
                "interpretation": form.get("interpretation", ""),
            }]}


async def _index(request, principal, *, form=None, error=None, status_code=200):
    active_jobs = await run_in_threadpool(jobs.list_active_jobs, principal)
    recent_jobs = await run_in_threadpool(jobs.list_jobs, principal)
    return render(request, "investigations.html", principal=principal,
                  active_jobs=active_jobs,
                  jobs=[job for job in recent_jobs if job["status"] in {"completed", "failed", "canceled"}],
                  domains=DOMAINS, sources=SOURCES, statuses=STATUSES, stage_label=stage_label,
                  form=form or {}, idempotency_key=(form or {}).get("idempotency_key") or uuid4().hex,
                  error=error, status_code=status_code)


@router.get("/investigations/active")
async def active_investigations(request: Request):
    principal = page_session(request)
    return render(request, "_active_investigations.html", principal=principal,
                  active_jobs=await run_in_threadpool(jobs.list_active_jobs, principal),
                  statuses=STATUSES, stage_label=stage_label)


@router.get("/investigations")
async def investigation_index(request: Request):
    return await _index(request, page_session(request))


@router.post("/investigations/new")
async def investigation_submit(request: Request):
    principal = page_session(request)
    if not principal.has_role("analyst"):
        raise permission_error("需要分析员或更高权限才能提交调查。")
    form = await _bounded_form(request)
    check_csrf(principal, form)
    try:
        value, _ = await run_in_threadpool(jobs.submit, principal, _payload(form), form.get("idempotency_key", ""))
    except ApiError as exc:
        return await _index(request, principal, form=form, error=exc.message, status_code=exc.status_code)
    except ValueError as exc:
        return await _index(request, principal, form=form, error=str(exc)[:300], status_code=400)
    return RedirectResponse("/investigations/" + value["id"], status_code=303)


@router.get("/investigations/{job_id}")
async def investigation_detail(request: Request, job_id: str):
    principal = page_session(request)
    job = await run_in_threadpool(jobs.get_job, principal, job_id)
    return render(request, "investigation_job.html", principal=principal, job=job,
                  statuses=STATUSES, domains=DOMAINS, sources=SOURCES,
                  stage_label=stage_label, message_label=message_label,
                  report_text=json.dumps(job.get("report"), ensure_ascii=False, indent=2)
                  if job.get("report") is not None else None)


@router.post("/investigations/{job_id}/cancel")
async def investigation_cancel(request: Request, job_id: str):
    principal = page_session(request)
    if not principal.has_role("analyst"):
        raise permission_error("需要分析员或更高权限才能取消调查。")
    form = await _bounded_form(request)
    check_csrf(principal, form)
    await run_in_threadpool(jobs.cancel, principal, job_id)
    return RedirectResponse("/investigations/" + job_id, status_code=303)
