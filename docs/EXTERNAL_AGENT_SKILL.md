# 在自己的 Agent 中使用 CyberGuard

[中文文档导航](README.zh-CN.md) · [先部署服务端](WEB_ONBOARDING.zh-CN.md)

标准 Skill **v0.2.0** 让现有 Agent 把已授权材料和调查目标提交给 CyberGuard 后端，再取回任务状态与报告。分析由部署端的 AgentTeams Workers 完成；调用方 Agent 负责交互、提交与解释返回结果。源码位于 [`integrations/agent-skills/cyberguard`](../integrations/agent-skills/cyberguard/)，与 [`skills/`](../skills/) 中供 Worker 使用的角色 Skill 分开。

客户端需要文件访问和 Python 3.10+，不需要本机 Docker 或独立模型密钥。在线调查需要可用的服务端 AgentTeams 配置；安装 Skill 本身不部署后端。旧事件只读包和无需服务的合成离线演练继续保留。

## 从控制台连接（推荐）

1. 登录 `/connect`，选择 Codex、Claude Code 或 generic。默认用途是提交调查；读取已有事件时选择独立的只读用途。
2. 管理员可创建 30 天有效期、仅显示一次的专用凭据。调查用途固定为 `investigations:read` + `investigations:write`；只读用途固定为 `incidents:read`。也可复用权限合适的既有凭据，成员通过组织认可渠道取得凭据。
3. 在 Agent 所在机器将密钥保存到仓库之外、仅运行账户可读取的私有文件。页面只填写绝对路径，不把秘密放进聊天或源码。
4. 生成无密钥连接提示词并交给 Agent。它核查已安装版本，复用兼容安装；缺失时安装同一个标准包，旧版本不会被自动覆盖。
5. 调查用途运行 `check --investigations`；只读用途运行 `check`，可在成功后 `fetch` 所选事件。检查成功不证明写权限、Worker 可用或调查完成。
6. 安装连接不上传材料。用户要求提交指定材料后，Agent 才准备请求并调用 `submit`。也可直接打开 `/investigations` 使用单份文本表单或多份 JSON。

非回环部署须由管理员设置 `CYBERGUARD_CONSOLE_ORIGIN` 为 Agent 可访问的 HTTPS 来源地址，不含路径、查询或凭据；回环测试可使用 HTTP。localhost 指 Agent 所在机器，不一定是浏览器所在机器。网页不能自动探测本机安装或连接状态；本流程不提供托管云、OAuth 或通用远程 MCP。

## 提交与取回报告

在 Agent 执行环境配置 `CYBERGUARD_CONSOLE_URL` 和 `CYBERGUARD_SKILL_KEY_FILE`。请求格式见[调查任务与材料](INVESTIGATION_TASKS.md)，客户端接口见[连接参考](../integrations/agent-skills/cyberguard/references/connection.md)。将 `<skill>` 替换为实际安装目录，输出文件须是新文件：

```bash
python <skill>/scripts/cyberguard.py --version
python <skill>/scripts/cyberguard.py check --investigations
python <skill>/scripts/cyberguard.py submit request.json --idempotency-key <stable-key> --out receipt.json
python <skill>/scripts/cyberguard.py status <task-id> --out status.json
python <skill>/scripts/cyberguard.py result <task-id> --out report.json
```

保存回执中的真实任务 ID。请求结果不明确时，使用原幂等键重试同一提交；修改材料或目标使用新键。请求 `result` 不会把等待或失败状态伪装成成功。用户明确要求取消时，可运行 `cancel <task-id> --idempotency-key <stable-cancel-key>`；取消停止后续阶段，已经发出的远程推理可能继续完成。

任务在服务端 SQLite 中保存，后台按检查点推进，调用方断开不删除任务。默认仅创建任务的用户或 API key 可读取；管理员会话可查看部署内全部任务。不同 API key 即使由同一管理员创建，也不是同一任务主体。此边界不是多租户隔离承诺。旧 `incidents:read` 覆盖该部署事件，所选事件 ID 不缩小其权限。

接收 Agent、防火墙、EDR、蜜罐、服务器日志、财务记录、审计报告、司法文书及其他来源的文本。格式限纯文本、JSON、CSV、Markdown；不原生解析 PDF/Office 或抓取 URL。原文与提交者解释分开，哈希不证明来源真实。金融、法律和通用报告为人工复核草稿，不代表专业判断。提交材料将进入部署配置的 Worker/模型处理环境；调用方读取材料也可能使其进入调用方模型环境。

后台默认使用 AgentTeams 原生 Project/Task 调度。Leader 自行规划并委派调查和独立复核，Worker 提交报告，Leader 验收后由 Console 获取原生产物。见[后端部署及证明边界](AGENTTEAMS_TASK_SERVICE.md)。新任务不创建或执行安全处置动作。

## 离线试用：复制这段提示词

把下面的提示词粘贴到支持文件访问与命令执行的 Agent 中。源码会放在独立目录，Skill 安装到你已有的项目。

```text
请把 CyberGuard 调查 Skill 安装到我当前项目，并完成一次离线首次使用演练。

从 https://github.com/elsechord/CyberGuard 获取源码到独立目录，保留已有文件，
记录实际检出的提交版本。先阅读 docs/EXTERNAL_AGENT_SKILL.md 和
integrations/agent-skills/cyberguard/SKILL.md，检查 scripts/install-agent-skill.py。

Codex 使用 --agent codex，Claude Code 使用 --agent claude，
其他兼容宿主使用 --agent generic；--project 指向我已有的项目目录。
不要覆盖已安装的 Skill。

安装后读取实际安装位置的 SKILL.md，生成新的离线演练快照，分析：
仅凭 CPU 占用高，能否认定挖矿？引用 evidence_id，说明还缺什么证据，
并给出下一步最值得做的观察。注明输入为合成演练，分析由当前 Agent 完成。
不要部署服务、索要模型密钥或执行处置。
如果宿主无法运行此流程，请说明缺少的能力。
```

需要固定版本时，可指定包含本接入包的提交 SHA，并记录安装来源。自动发现可能需要宿主重新加载会话；首次演练可以直接读取已安装的 `SKILL.md` 执行，不能以“文件已复制”代替“宿主已发现”的验证。

## 不使用安装提示词时

在含本接入包的 CyberGuard 源码目录运行（目标目录必须已存在）：

```bash
python scripts/install-agent-skill.py --agent codex --project /absolute/path/to/project
# Claude Code 改为 --agent claude
```

安装器只复制独立包，不安装依赖、不访问网络、不修改全局配置、不覆盖已有安装。Codex / generic 目标为 `.agents/skills/cyberguard`，Claude Code 为 `.claude/skills/cyberguard`。也可以手动复制整个独立包目录到宿主支持的位置。包内保留 Apache-2.0 许可证。

## 读取既有事件包

保留旧的离线 `inspect` 和在线 `check` / `fetch` 路径。离线可读取含 `summary` 与 `evidence` 的 CyberGuard 事件详情，或 console 的 `{"data": ...}` 包装；在线需要独立的 `incidents:read` 凭据：

```bash
python <skill>/scripts/cyberguard.py check
python <skill>/scripts/cyberguard.py fetch CG-2026-0001 --out incident.json
```

事件 ID 须真实存在。调用方 Agent 分析这个包；这些命令不创建后端任务。列表为空是成功连接但无数据，401/403、网络和上游错误不能解释成空列表，不应自动换用更宽权限或猜测其他地址。

## 宿主兼容与验证边界

支持 Skill、文件读取和 Python 执行的宿主可使用标准包，Codex / generic 与 Claude Code 选项只改变安装布局。安装和客户端有本地测试，应用内自动发现需要分别验收。自定义 HTTP 工具可按任务 API 适配；仅支持 MCP 的宿主仍需实际 MCP 服务，不能把仓库内部 AgentTeams 配置当作通用外部服务。仅能聊天的宿主不能凭提示词建立实时连接。

企业自有 Agent 的兼容性须逐个平台核查；这里不宣称已验证厂商平台或存在合作。安装、连接检查、真实任务提交、报告引用及失败处理应分别验证；离线演练不能替代在线验收。官方入口研究见 [Agent 接入调研](AGENT_ONBOARDING_RESEARCH.md)，来源追踪与安全接入依据见[基础设施调研](INVESTIGATION_INFRA_RESEARCH.md)。
