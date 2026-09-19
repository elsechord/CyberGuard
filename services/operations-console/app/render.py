"""Jinja2 rendering with auto-escaping. All templates live in app/templates."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from . import auth, config

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.trim_blocks = True
templates.env.lstrip_blocks = True

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
    context.setdefault(
        "nav_principal",
        auth.session_principal(request.cookies.get(config.cookie_name(), "")))
    notice = request.query_params.get("notice")
    if notice:
        context.setdefault("toast", NOTICES.get(notice, ""))
    return templates.TemplateResponse(request=request, name=template,
                                      context=context, status_code=status_code)
