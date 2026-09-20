# 多用户控制台使用说明

[English](OPERATIONS_CONSOLE.md) · [中文文档导航](README.zh-CN.md)

Console 是 CyberGuard 部署中的多用户操作入口。已认证用户或 API Key 可查看事件、推进调查工作流、批准或拒绝处置提案、查看模型预算，以及导出控制台认证审计。处置审批必须填写分类和意见，底层证据与动作仍由网关和执行器保存。

服务目录为 `services/operations-console`，内部监听 8080，Compose 映射到 `127.0.0.1:18120`。本地状态保存在 SQLite `console.db`；密码与 API Key 只保存摘要。跨服务调用使用网关、执行器、预算服务的 HTTP API。

## 部署配置

完整启动与备份流程见[部署手册](OPERATIONS_DEPLOY.zh-CN.md)。数据库目录需可写，其他主要参数如下：

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `CYBERGUARD_CONSOLE_DB` | SQLite 路径 | `/data/console.db` |
| `CYBERGUARD_GATEWAY_URL` | 证据网关 origin | 空；事件功能提示不可用 |
| `CYBERGUARD_GATEWAY_TOKEN` | 网关 bearer 凭据 | 空 |
| `CYBERGUARD_EXECUTOR_URL` | 响应执行器 origin | 空；审批功能提示不可用 |
| `CYBERGUARD_EXECUTOR_TOKEN` | 执行器 bearer 凭据 | 空 |
| `CYBERGUARD_EXECUTOR_APPROVAL_SECRET` | `/actions/approve` 使用的审批秘密 | 空 |
| `CYBERGUARD_GUARD_URL` | 可选预算服务 origin | 空；账本显示不可用 |
| `CYBERGUARD_GUARD_ADMIN_TOKEN` | 可选预算服务管理凭据 | 空 |
| `CYBERGUARD_COOKIE_SECURE` | Cookie 是否带 Secure；HTTPS 应保持 true | `true` |
| `CYBERGUARD_CONSOLE_ORIGIN` | 代理后的标准公开 origin，也用于 CSRF | 空 |
| `CYBERGUARD_UPSTREAM_TIMEOUT` | 上游请求超时秒数 | `5` |
| `CYBERGUARD_LOGIN_BACKOFF_BASE` | 登录指数退避的基础秒数 | `1` |

可选依赖缺失时页面显示状态说明，不会让整个 Console 崩溃；代理 API 以统一错误格式返回 502/503。调查后端另需[原生任务配置](AGENTTEAMS_TASK_SERVICE.md)。

## 首次管理员

空数据库首次启动会生成一次性 setup token，完整值仅打印在容器日志的 `CYBERGUARD SETUP TOKEN (first boot only): …` 行中。打开 `/setup`，从日志复制完整值并创建管理员；页面仅显示掩码预览。

也可以使用 CLI：

```bash
docker compose exec operations-console python -m app.bootstrap admin <username>
```

CLI 从 `CYBERGUARD_BOOTSTRAP_ADMIN_PASSWORD` 读取密码，未设置时交互输入。首个管理员创建后 `/setup` 永久关闭，setup token 清除。数据库保存 `pbkdf2_sha256$600000$<salt>$<digest>`，不保存明文密码。

## 权限角色

角色权限逐级累加，每条路由都有最低权限要求：

| 能力 | viewer | analyst | approver | admin |
| --- | --- | --- | --- | --- |
| 只读页面及 GET API | ✓ | ✓ | ✓ | ✓ |
| 评论、非审批工作流流转 | — | ✓ | ✓ | ✓ |
| 批准／拒绝提案，填写分类和意见 | — | — | ✓ | ✓ |
| 成员、角色、API Key、审计导出 | — | — | — | ✓ |

未认证 API 返回 401，网页跳转 `/login`；权限不足返回 403。两类事件均记录到 `auth_event`。改变成员角色或禁用成员，会立即失效该成员所有会话。

## 调查与连接入口

- `/connect`：选择调用方 Agent、生成 Skill 连接提示词与专用凭据，详见[连接 Agent](EXTERNAL_AGENT_SKILL.md)。
- `/investigations`：提交目标和材料、跟踪原生任务、读取最终报告，详见[调查任务](INVESTIGATION_TASKS.md)。
- 事件与审批页面：查看网关证据及执行器提案；批准不是独立效果复核，执行后仍需检查实际结果。

## API v1

`/api/v1` 支持浏览器会话 Cookie 或 `Authorization: Bearer cg_live_…` API Key。会话 JSON 请求必须同源，并携带 `Origin`／`Referer` 与 `X-Requested-With`；API Key 请求不使用 CSRF 检查。

列表统一返回 `{"data": [...], "has_more": bool, "next_cursor": "<last id>" | null}`。`limit` 默认 20、最大 100；`cursor` 是上次最后一条记录 ID。错误统一为 `{"error": {"type": ..., "code": ..., "message": ...}}`，类型包括 `invalid_request_error`、`authentication_error`、`permission_error`、`idempotency_error`、`api_error`。

| 端点 | scope | 用途 |
| --- | --- | --- |
| `GET /api/v1/incidents` | `incidents:read` | 网关事件摘要，可按 `status=` 过滤 |
| `GET /api/v1/incidents/{id}` | `incidents:read` | 证据、动作与工作流详情 |
| `POST /api/v1/incidents/{id}/workflow` | `incidents:write` | 请求体 `{state, message, session_id?}`；非法流转返回网关 409 |
| `GET /api/v1/proposals` | `incidents:read` | 从动作审计获取提案，可按状态过滤 |
| `POST /api/v1/proposals/{id}/decision` | `decisions:write` | `{action: approve\|deny, classification, comment}`；批准时携带服务端审批秘密调用执行器，所有决定均本地留存 |
| `GET /api/v1/audit-events` | `audit:read` | 认证与操作审计 |
| `GET/POST /api/v1/keys`、`DELETE /api/v1/keys/{id}` | `keys:admin` | 管理 API Key；创建时仅展示一次明文 |
| `GET /api/v1/usage/summary` | `usage:read` | 模型预算汇总，未配置时 `{"available": false}` |

基础 scope 为 `incidents:read`、`incidents:write`、`decisions:write`、`audit:read`、`usage:read`、`keys:admin` 与全权 `admin`。调查 API 还使用 `investigations:read` / `investigations:write`，端点与任务归属规则见[调查任务](INVESTIGATION_TASKS.md)。会话使用角色对应权限，API Key 仅使用签发时授予的 scope。

写接口支持 `Idempotency-Key`，最长 255 字符、保留 24 小时。同键同参数返回原响应并带 `Idempotent-Replay: true`；同键不同参数返回 409 `idempotency_error`。

审批分类必须为 `approved_true_positive`、`approved_with_caution`、`denied_false_positive_logic`、`denied_false_positive_data`、`undetermined` 之一，意见至少 4 个字符。缺少或不识别的分类返回 422。

以下 `cg_live_…` 是占位值，需替换成自己的凭据：

```bash
# 查看提案
curl -s -H "Authorization: Bearer cg_live_…" \
  http://127.0.0.1:18120/api/v1/proposals | jq .

# 批准指定提案；提案 ID 也应替换为实际值
curl -s -X POST http://127.0.0.1:18120/api/v1/proposals/ACT-9c2f11d04a8e/decision \
  -H "Authorization: Bearer cg_live_…" \
  -H "Idempotency-Key: approve-act-9c2f-0001" \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","classification":"approved_true_positive",
       "comment":"已核对独立证据与目标业务影响"}' | jq .

# 分页查看审计
curl -s -H "Authorization: Bearer cg_live_…" \
  "http://127.0.0.1:18120/api/v1/audit-events?limit=20" | jq .
```

## 会话与安全机制

- 密码采用 PBKDF2-HMAC-SHA256、600,000 次迭代、16 字节随机盐和常量时间比较。未知用户也执行完整虚拟派生，减少通过耗时枚举账户。
- 会话 ID 为 32 字节随机值，数据库仅保存 SHA256；Cookie 默认 `__Host-cgsession`，带 `HttpOnly; Secure; SameSite=Lax; Path=/`。闲置 30 分钟或总时长 8 小时失效；登录、注销和权限变化会轮换或清除会话。本机 HTTP 模式使用不带 `__Host-` 的 `cgsession`。
- 登录失败按账户计数，连续失败后按 1/2/4/8 秒退避，第五次锁定 15 分钟；错误提示统一。
- 会话表单使用同步 CSRF token；登录／setup 的会话前表单使用短时 HMAC token。
- 响应带 CSP、`X-Content-Type-Options`、`Referrer-Policy: no-referrer`、`X-Frame-Options: DENY` 与 `Cache-Control: no-store`。Jinja2 默认转义，页面不依赖内联脚本或样式。
- API Key 为 `cg_live_` 加 32 字节随机值，存储 SHA256，展示 14 字符前缀，支持过期与撤销，明文只显示一次；最近使用时间更新会节流。
- `auth_event` 追加记录登录、锁定、拒绝、审批、密钥生命周期和导出；管理员可导出 CSV。
- 上游调用使用禁用代理和重定向的 urllib，默认 5 秒超时、4 MiB 响应上限，阻塞请求在线程池执行，不记录 token。

Console 信任容器之间的内部网络，不抵御已经被控制的网关或执行器。当前速率限制集中在登录，通用入口限流可由受控代理提供。Console 认证审计由 SQLite 事务保证追加操作，不是执行器的 HMAC 链；需要留存时导出 `/audit/export.csv`。生产 Cookie 应经 HTTPS 传输。

## 数据备份

Console 数据包括用户、会话摘要、API Key 摘要、评论、决定、调查材料／状态／报告与认证审计；网关／执行器仍是证据和响应动作的原始存储。请用[一致性导出与恢复流程](OPERATIONS_DEPLOY.zh-CN.md#备份)备份，不要直接复制正在写入的数据库。丢失该数据库会丢失控制台本地账户和记录，需要从备份恢复。
