# 在自己的 Agent 中使用 CyberGuard

CyberGuard 的外部 Skill 让你保留现有 Agent 和模型，在当前对话里分析 CyberGuard 事件：读取证据、比较不同解释、指出调查缺口，并给出带证据引用的结论。

这是第一版 **0.1.0，只读调查接入**。代码位于 [`integrations/agent-skills/cyberguard`](../integrations/agent-skills/cyberguard/)。它与 [`skills/`](../skills/) 下供 AgentTeams Worker 使用的十个角色 Skill 分开分发。外部 Skill 不要求安装 AgentTeams，不另行调用模型，也不执行处置。

## 复制这段提示词

以下提示词用于**已经包含本接入包的本地源码目录**。把两个路径替换成实际路径后，粘贴到支持文件与命令执行的 Agent 中：

```text
请把 CyberGuard 的外部调查 Skill 安装到我当前项目，并完成一次首次使用演练。

CyberGuard 源码目录：<包含本接入包的源码绝对路径>
安装目标项目：<当前项目绝对路径>

先阅读源码中的 docs/EXTERNAL_AGENT_SKILL.md 和
integrations/agent-skills/cyberguard/SKILL.md，检查随附脚本。
使用 Python 3.10+ 执行 scripts/install-agent-skill.py：
Codex 使用 --agent codex，Claude Code 使用 --agent claude，
其他兼容 .agents/skills 的宿主使用 --agent generic；
--project 指向上面的目标项目。已有安装时停止覆盖，说明现有版本。

安装后读取实际安装位置的 SKILL.md，生成一份新的离线演练快照，
读取完整证据，回答：CPU 占用高是否足以认定挖矿？下一步最值得查什么？
给出 evidence_id 引用，并说明这是合成演练，分析由当前 Agent 完成。
不要部署服务、索要模型密钥或执行任何处置。
如果宿主不支持安装 Skill 或运行工具，请说明缺少什么，不要宣称安装成功。
```

当前开发工作区的源码路径为 `D:/Projects/CyberGuard/research-source`；对外分享时必须换成接收方自己的路径。自动发现可能需要宿主重新加载会话；首次演练可以直接读取已安装的 `SKILL.md` 执行，不能以“文件已复制”代替“宿主已发现”的验证。

### 面向公开仓库的提示词（发布后使用）

仅在包含这些文件的提交已推送后使用，并把 `<发布提交 SHA>` 换成实际值。已有旧版公开仓库或旧版 Release 不等于包含此外部 Skill。

```text
请从 https://github.com/elsechord/CyberGuard 获取提交 <发布提交 SHA>，
保留我现有项目与已有安装，不执行远程下载的 shell 一行脚本。
阅读 docs/EXTERNAL_AGENT_SKILL.md，检查外部 Skill 的代码，
按其中“复制这段提示词”的流程，将 Skill 安装到当前项目并完成离线演练。
如果该提交没有文档或安装脚本，请停止并报告版本不匹配。
```

## 不使用安装提示词时

在含本接入包的 CyberGuard 源码目录运行（目标目录必须已存在）：

```bash
python scripts/install-agent-skill.py --agent codex --project /absolute/path/to/project
# Claude Code 改为 --agent claude
```

安装器只复制独立包，不安装依赖、不访问网络、不修改全局配置、不覆盖已有安装。Codex / generic 目标为 `.agents/skills/cyberguard`，Claude Code 为 `.claude/skills/cyberguard`。也可以手动复制整个独立包目录到宿主支持的位置。包内保留 Apache-2.0 许可证。

## 接入自己的事件

**离线导出：** 将现有 CyberGuard operations console 事件响应或 gateway 事件详情 JSON 交给 Agent。可以使用 console 的 `{"data": ...}` 包装，也可以直接使用含 `summary` 与 `evidence` 的事件详情。此版本不直接解析任意 PDF、日志文件或调查归档包。

**在线读取：** 先有可访问的 CyberGuard operations console，由管理员生成仅带 `incidents:read` scope 的 API key，在 Agent 的执行环境中配置：

- `CYBERGUARD_CONSOLE_URL`：控制台来源地址，例如 `https://cyberguard.internal.example`。不是 evidence gateway 地址。
- `CYBERGUARD_SKILL_KEY_FILE`：仅供运行账户读取的密钥文件绝对路径。不要把密钥粘贴到聊天、仓库或安装提示词中。

具体连接、错误处理和权限边界见 [connection.md](../integrations/agent-skills/cyberguard/references/connection.md)。当前服务的 scope 不是按租户或事件隔离的授权；跨客户部署仍需分别规划隔离。

配置完成后，可以对 Agent 说：

```text
使用 CyberGuard Skill 调查事件 CG-2026-0001。
读取已配置的 CyberGuard 控制台证据，比较恶意活动与正常业务的解释，
引用证据并列出仍缺失的观察。把报告保存在当前项目中，不执行处置。
```

事件 ID 必须替换为实际存在的事件。离线演练不需要服务、账号或模型密钥；真实在线读取需要服务与授权。离线客户端不联网不代表宿主模型在本地运行，数据处理位置取决于你使用的 Agent。

## 哪些 Agent 可以接入

| 宿主能力 | 接入方式 | 当前验证范围 |
| --- | --- | --- |
| 支持 Skill、文件读取和 Python 执行 | 安装本包，读取快照或调用客户端 | 已实现安装布局；用隔离目录与本地 HTTP 服务测试。尚未逐一完成 Codex / Claude Code 应用内自动发现验收 |
| 支持自定义 HTTP 工具 | 管理员注册事件读取 API，并提供调查说明 | 可用现有 console API 适配；本包没有自动配置企业平台 |
| 只支持 MCP 工具 | 需要注册一个实际 MCP 服务 | 此版本未提供外部 MCP 服务；仓库现有 AgentTeams MCP 配置不能直接当作通用外部服务 |
| 只能发送聊天文字 | 无法仅靠提示词建立实时连接 | 可解释用户提供的文本，但不能宣称已安装或调用 CyberGuard |

安恒、微步、德勤、摩根等自有 Agent 是否支持这些接口，需要逐个平台确认；这里不代表已验证兼容或存在合作关系。

## 当前交付与下一步

当前交付覆盖安装、离线首次使用、读取既有事件、调用方分析和本地报告。它尚不覆盖新事件创建、向设备取证、报告回写、任务订阅、处置执行或跨行业审计。Skill 是接入入口；可复用的实际能力还来自事件 API、证据组织与调查方法。

接下来应在两个独立宿主中完成同一真实事件的使用验收，再补企业平台需要的 MCP / HTTP 工具接入，以及按客户场景选择的新取证能力。评审演示应同时展示安装、真实工具调用、证据引用与失败处理，而不只展示一段安装提示词。

参考：[Cloudflare Skills](https://github.com/cloudflare/skills)、[Agent Skills 规范](https://agentskills.io/specification)、[Codex Skills](https://developers.openai.com/zh-Hans/docs/build-skills)、[Claude Code Skills](https://code.claude.com/docs/en/skills)。
