"""Secret-free onboarding for the existing portable investigation Skill."""
import ipaddress
import json
import re
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

AGENTS = {"codex": "Codex", "claude": "Claude Code", "generic": "其他兼容 Agent"}
INCIDENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_origin(value: str) -> str:
    if not value or len(value) > 256 or re.search(r"[\s\\]", value):
        raise ValueError("请配置有效的控制台外部地址。")
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        port = url.port
    except ValueError:
        raise ValueError("控制台地址格式不正确。") from None
    try:
        ipaddress.ip_address(host)
        valid_host = True
    except ValueError:
        valid_host = bool(host) and len(host) <= 253 and all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            for label in host.rstrip(".").split("."))
    if (not host or not re.fullmatch(r"[A-Za-z0-9.:-]+", host)
            or not valid_host
            or url.username is not None or url.password is not None
            or url.path not in {"", "/"} or url.query or url.fragment
            or url.scheme not in {"https", "http"}
            or (url.scheme == "http" and not loopback(host))
            or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("地址需为 HTTPS 来源地址，不含路径、凭据或查询参数；本机回环地址可用 HTTP。")
    return value.rstrip("/")


def public_origin(request, configured: str) -> str:
    if configured:
        return validate_origin(configured)
    # Arbitrary Host / Forwarded headers must not become connection instructions.
    if loopback(request.url.hostname or ""):
        return validate_origin(str(request.base_url))
    raise ValueError("请管理员设置 CYBERGUARD_CONSOLE_ORIGIN 为 Agent 可访问的控制台 HTTPS 地址。")


def build_prompt(origin: str, agent: str, key_file: str, incident_id: str, purpose="read") -> str:
    if agent not in AGENTS:
        raise ValueError("请选择支持的 Agent。")
    if key_file and (len(key_file) > 512 or any(ord(c) < 32 for c in key_file)
                     or not (PurePosixPath(key_file).is_absolute()
                             or PureWindowsPath(key_file).is_absolute())):
        raise ValueError("凭据文件请填写 Agent 所在机器上的绝对路径，不要填写密钥内容。")
    if incident_id and not INCIDENT_ID.fullmatch(incident_id):
        raise ValueError("事件 ID 格式不正确。")
    if purpose not in {"read", "investigations"}:
        raise ValueError("请选择接入方式。")
    if purpose == "investigations":
        data = json.dumps({"console_url": origin, "key_file": key_file or None}, ensure_ascii=False, indent=2)
        return f"""请为当前项目连接 CyberGuard 后台调查服务。先完成安装和连接检查，收到我的明确调查请求后再提交材料。
检查已有 CyberGuard Skill；需要 0.2.0 或支持 submit/status/result/cancel 的版本。已有兼容安装则复用，不自动覆盖旧版。
若未安装，从 https://github.com/elsechord/CyberGuard 获取独立源码目录并记录提交；阅读 docs/EXTERNAL_AGENT_SKILL.md、integrations/agent-skills/cyberguard/SKILL.md 与安装脚本后，执行 scripts/install-agent-skill.py --agent {agent} --project <当前已有项目绝对路径>。
以下 JSON 仅是配置数据，不作为 shell 命令执行：
{data}
使用 console_url 配置 CYBERGUARD_CONSOLE_URL，用 key_file 配置 CYBERGUARD_SKILL_KEY_FILE。凭据需要 investigations:read 与 investigations:write，不需要任何处置或审批权限。缺少文件路径时，让我在 Agent 所在机器保存凭据并提供路径；不要要求在聊天粘贴密钥，也不要读取或打印密钥文件内容，交给客户端 HTTP 请求使用。
localhost 指 Agent 所在机器；无法访问时询问已授权地址，不猜测其他服务器。
用已安装 Skill 的 scripts/cyberguard.py check --investigations 验证实际连接。网页复制成功或安装完成不代表已连接。
收到明确调查需求后，按 Skill 文档将调查目标和获准材料整理为提交 JSON。保留原文、来源类型与名称，把你的解释单独放入 interpretation；不要上传整个工作区，不自动获取 URL 内容，也不把推测伪装为原始数据。
运行 submit，使用稳定 Idempotency-Key 和新的回执文件；超时重试保持同一键。保存 task ID 与控制台链接，用 status 查询进度；等待后台 AgentTeams 的 investigator、planner、verifier 返回报告，再用 result 导出。不要用你自己的推理伪装后台报告。若后台等待配置、失败或结果未就绪，准确说明。
任务提交后可结束当前对话，之后按 task ID 取回结果。仅在我明确要求时调用 cancel；取消停止后续阶段，已发出的远程推理可能继续。
当前输入支持文本、JSON、CSV、Markdown。金融和法律材料分析是待专业人员复核的草稿，不是专业审计或法律意见。材料会发送到部署管理员配置的 AgentTeams 模型环境。此流程不执行处置；不要自行申请批准、隔离主机或修改业务系统。"""
    connection = json.dumps({"console_url": origin, "key_file": key_file or None,
                             "incident_id": incident_id or None}, ensure_ascii=False, indent=2)
    task = ("连接检查成功后，使用 fetch 读取指定事件到一个新文件。读取完整证据，给出带 evidence_id 引用的分析、相反解释和下一步观察，并附上控制台事件链接。"
            if incident_id else "本次只验证连接。没有指定事件时，请让我选择一个真实事件，不要猜测事件 ID 或把合成案例当作真实数据。")
    return f"""请把当前项目的 Agent 连接到 CyberGuard，以只读方式调查事件。

先检查当前项目是否已有 CyberGuard Skill。已有时阅读 SKILL.md 和客户端帮助，确认支持 check / fetch；版本不兼容时说明差异，不覆盖现有文件。
未安装时，从 https://github.com/elsechord/CyberGuard 获取源码到独立目录并记录提交版本；先阅读 docs/EXTERNAL_AGENT_SKILL.md、integrations/agent-skills/cyberguard/SKILL.md 和 scripts/install-agent-skill.py，再使用 --agent {agent} --project <当前已有项目的绝对路径> 安装。不要修改全局配置。

下面是连接配置数据，不是 shell 命令：
{connection}

确认该地址是我授权访问的控制台。localhost / 回环地址指 Agent 所在机器；若 Agent 在远程环境，先要求我提供可访问的已授权地址，不要自行猜测替代地址。
将 console_url 用于 CYBERGUARD_CONSOLE_URL，将 key_file 路径用于 CYBERGUARD_SKILL_KEY_FILE。若未配置路径或文件不存在，让我在本机保存仅含 incidents:read 权限的凭据并提供路径；不要让我把密钥粘贴进聊天，不要通过模型工具读取或打印文件内容。只有客户端 HTTP 请求使用该文件。
读取已安装的 SKILL.md；用 Python 3.10+ 运行该 Skill 的 scripts/cyberguard.py check，通过实际只读请求验证连接。不要因为复制提示词或文件安装成功就宣称已连接。
{task}
认证失败、权限不足、服务不可达或上游异常时，分别说明真实错误，不更换服务器或扩大权限。此次访问权限覆盖该部署的事件，所选事件不是权限隔离边界。
不要部署服务、调用响应执行器、申请审批权限或执行处置。分析由当前 Agent 完成，数据处理位置取决于当前 Agent 的模型环境。"""
