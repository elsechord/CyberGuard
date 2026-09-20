"""Jinja2 rendering with auto-escaping. All templates live in app/templates."""
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates

from . import auth, config

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.trim_blocks = True
templates.env.lstrip_blocks = True


def _fmt_ts(value):
    """Render ISO timestamps as 'YYYY-MM-DD HH:MM UTC'; pass through anything else."""
    if not value:
        return "—"
    text = str(value)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


templates.env.filters["ts"] = _fmt_ts

# Presentation only: API values, submitted form values and unknown states stay intact.
STATUS_LABELS = {
    "received": "已接收", "investigating": "调查中",
    "evidence_validation": "证据核验中", "awaiting_approval": "待审批",
    "pending_approval": "待审批", "approved": "已批准", "rejected": "已拒绝",
    "executing": "执行中", "responding": "处置中", "completed": "已完成",
    "verified": "已核验", "rolled_back": "已回滚", "failed": "失败",
    "timed_out": "超时", "audit_error": "审计异常",
}
templates.env.filters["status_label"] = lambda value: STATUS_LABELS.get(value, value)

NOTICES = {
    "admin-created": "管理员已创建，请登录。",
    "workflow-ok": "工作流状态已更新。",
    "workflow-failed": "工作流变迁被拒绝，请检查状态是否合法。",
    "comment-ok": "评论已发表。",
    "decision-recorded": "决策已记录。",
    "member-created": "成员已创建。",
    "role-updated": "角色已更新，该用户的所有会话已失效。",
    "member-updated": "成员状态已更新。",
    "key-revoked": "API key 已吊销。",
    "invalid-scopes": "无效的 scope 列表。",
}


def render(request, template: str, status_code: int = 200, **context):
    context.setdefault("studio_mode", os.getenv("CYBERGUARD_MODELSCOPE_EMBED", "").strip() == "1")
    context.setdefault(
        "nav_principal",
        auth.session_principal(request.cookies.get(config.cookie_name(), "")))
    notice = request.query_params.get("notice")
    if notice:
        context.setdefault("toast", NOTICES.get(notice, ""))
    return templates.TemplateResponse(request=request, name=template,
                                      context=context, status_code=status_code)
