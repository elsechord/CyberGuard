# Agent 接入入口调研

核验日期：2026-09-20。范围为官方公开文档；未登录竞品控制台逐项验收，文档中的客户端支持不代表 CyberGuard 已在相同客户端完成实机验证。

| 官方产品 | 文档中已有的做法 | 对 CyberGuard 的启发 |
| --- | --- | --- |
| [Supabase AI Tools](https://supabase.com/docs/guides/ai-tools) | 先选择 Agent；区分 MCP 实时连接、Skills 操作知识、Plugin 打包安装和提示词入口 | 用户入口围绕连接任务，底层仍使用一个标准 Skill |
| [Supabase MCP](https://supabase.com/docs/guides/ai-tools/mcp) | 选择项目、只读选项和客户端，生成配置；授权后以实际查询验证 | 生成当前上下文的指令；安装与实际访问分别验证 |
| [Sentry MCP](https://mcp.sentry.dev/) | 按组织或项目限制连接 URL；为 Claude Code、Cursor、VS Code 提供不同配置方式，首次连接走 OAuth | 预填调查上下文；客户端差异由入口消化 |
| [Cloudflare Agent setup](https://developers.cloudflare.com/agent-setup/) 与 [Cursor 指南](https://developers.cloudflare.com/agent-setup/cursor/) | 客户端专属短流程，安装插件后试用 prompt；工具访问另行授权 | 安装说明后给出可验证的首次任务 |
| [Supabase Plugin](https://supabase.com/docs/guides/ai-tools/plugins) | 打包 MCP 与 Skills，支持项目或全局安装 | 能力安装可以复用，不应把每次连接都变成重装 |

以上为来源当前明确描述的功能，并非把厂商路线图当作已交付能力。下述是 CyberGuard 本次实现边界；不能据此宣称具有竞品 MCP 或 OAuth 能力。

## 已交付入口与执行边界

- 登录后 `/connect` 默认调查用途，为 Skill v0.2.0 生成不含密钥的提示词。管理员可创建固定 `investigations:read` + `investigations:write`、30 天有效期的凭据。独立的旧只读用途使用 `incidents:read`。
- Codex、Claude Code、generic 复用标准包，仅适配安装布局；已有兼容安装不自动覆盖。私有凭据留在 Agent 机器，提示词只携带文件路径。
- 非回环地址来自管理员配置的 `CYBERGUARD_CONSOLE_ORIGIN`。安装后用 `check --investigations` 验证任务读取权限，不自动提交材料，也不证明写权限或推理后端就绪。
- 用户授权指定材料后，客户端提交目标和多源文本，再获取持久化任务状态与报告。也可在 `/investigations` 使用简易文本表单或完整 JSON。纯文本、JSON、CSV、Markdown 是当前范围，没有原生 PDF/Office 解析或任意 URL 抓取。
- 服务端 SQLite 保存队列、原文、独立解释、阶段检查点和报告；调用方断开不删除任务。取消停止后续阶段，已发出的远程推理可能仍在运行。
- 后端使用 AgentTeams 原生 Project/Task，由 Leader 规划、委派并验收；调用方 Agent 是材料提交与结果获取入口。调查任务不执行处置动作。
- 财务、法律和通用文本可接入，但报告是待人工复核草稿，不宣称专业领域判断。缺少后端时明确显示等待/失败，不用离线演练或本地分析冒充后端结果。
- 旧事件只读和合成离线演练保留；该路径由调用方分析，不能证明在线任务完成。

调查任务按创建者用户或 API key 隔离，管理员会话可查看当前部署内全部任务；这不是跨租户隔离承诺。旧事件读取权限覆盖当前部署，事件选择仅设定上下文。数据会进入实际调用方或后端配置的模型处理环境。当前没有托管云、OAuth 或通用外部 MCP。

## 后续验证

OAuth/一次性配对、远程 MCP 和租户级隔离仍需实现与独立验收。原生 Task 接入见 AGENTTEAMS_TASK_SERVICE.md。当前实现需在独立宿主和真实配置的 Workers 上验证安装发现、身份与权限、提交幂等、断连恢复、引用及失败处理；本地测试不等于生产验收。

使用方式见 [Skill 安装与连接](EXTERNAL_AGENT_SKILL.md)，运行边界见 [AgentTeams 任务服务](AGENTTEAMS_TASK_SERVICE.md)，接入与引用依据见[基础设施研究](INVESTIGATION_INFRA_RESEARCH.md)。
