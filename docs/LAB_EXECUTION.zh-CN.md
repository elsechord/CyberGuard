# 真实账号操作实验

[English](LAB_EXECUTION.md) · [中文文档导航](README.zh-CN.md)

本实验在独立的 SQLite 身份服务中禁用并恢复 `compromised-lab`，同时确认 `control-lab` 始终可访问。它验证服务间的真实操作与复核，不是生产身份连接器、攻击检测基准或新的 AgentTeams 在线任务。

## 安装与复现

使用 Python 3.12+ 和一次性虚拟环境，在仓库根目录运行。需要完整源码，包括 `tests/lab_support.py`。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r services/security-tool-gateway/requirements.txt
.\.venv\Scripts\python -m pip install --require-hashes --no-deps -r tests/requirements.lock
.\.venv\Scripts\python -m pip check
.\.venv\Scripts\python scripts/lab-demo.py
```

Windows 安装固定直接依赖版本，间接依赖由 pip 解析，与 Linux 的完整哈希锁定环境不同。测试依赖文件补充 `httpx`、`httpcore`、`certifi`，其余依赖由服务安装提供，并通过 `pip check` 检查。

Linux x86_64 / CPython 3.12（现有服务锁文件对应的平台）：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r services/requirements.lock -r tests/requirements.lock
.venv/bin/python -m pip check
.venv/bin/python scripts/lab-demo.py
```

运行全部本地测试：Windows 使用 `powershell -ExecutionPolicy Bypass -File scripts/test-local.ps1`，Linux 使用 `bash scripts/test-local.sh`。仅运行故障注入测试：`python tests/test_lab_execution.py`。

演示在三个空闲回环端口启动身份服务、执行器和网关，为不同角色生成随机凭据，使用临时数据库与审计目录，不接收生产 URL 或凭据。退出时清理进程和私有临时状态，输出只包含证据。检查失败时以非零状态退出并保留失败清单。共 17 项检查，包含按运行导出。

## 使用 Docker

准备可运行 Linux 容器的 Docker：

```bash
docker compose -f compose.lab.yaml up --build --abort-on-container-exit --exit-code-from lab
mkdir -p artifacts/docker-lab
docker compose -f compose.lab.yaml cp lab:/artifacts/. artifacts/docker-lab/
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=128m cyberguard/lab:local python tests/test_lab_execution.py
```

实验镜像将三个服务和测试框架放在一个非 root 容器中，通过容器自身回环接口通信。运行时关闭网络，不暴露宿主端口，可写状态位于临时文件系统；证据保存在 `cyberguard-lab_lab-artifacts` 专用卷。构建时需要联网下载固定依赖，运行时无需模型密钥、`.env`、生产凭据或 AgentTeams。

构建前可将 `CYBERGUARD_SOURCE_COMMIT` 设为 `git rev-parse HEAD` 以记录源码来源。该参数是构建方声明，不是工作区干净的证明。容器导出对所含源文件计算哈希，来源标记为 `exported_source`，`git_dirty=null`；原生 Git 运行保留真实 dirty 标记。容器源码快照包含服务、脚本、测试、场景和知识目录，不是完整 Git checkout。

基础服务 Compose 默认使用模拟执行，和本实验独立。该实验不连接 AgentTeams 容器网络，也不是生产部署方案。CI 会构建、运行实验，保留证据并执行故障注入测试。

## 输出产物

`artifacts/lab/LAB-<uuid>/` 包含：

- `manifest.json`：运行、动作和环境标识，模型/执行模式，时间戳与逐项检查结果。
- `trace.json`：提案、未审批执行被拒、审批、执行、独立访问观测、回滚和审计验证回执。
- `action-history.json`：执行器的 HMAC 链记录，不导出签名密钥。
- `run-export.json`：只包含本事件/本轮运行的证据与已认证动作，附各动作状态和最新适用观测。
- `source-tree.json`：Git 提交、工作区修改标记，以及当前被跟踪/未忽略源文件的哈希。工作区有修改时明确标注。
- `SHA256SUMS`：上述 JSON 的完整性校验值。校验值本身不能认证产物作者；离线 HMAC 验证需要单独保存的密钥。

测试框架检查执行前和回滚后的真实访问情况。中间阶段由网关以两个账号分别发起携带新 nonce 的 HTTP 请求；执行器返回成功本身不会把复核结论设为 `verified`。

## 按运行划分的 API 与控制台

所有工具调用可携带顶层 `run_id`。实验复核必须提供它，同时兼容 `arguments.run_id`；两处冲突时在采集前拒绝。新证据包括服务端生成的 `tool_call_id`、`scenario_id`、环境/执行标签和 `envelope_sha256`。封装摘要覆盖运行关联与序列化证据，原有 `sha256` 仍对应源记录。哈希可以发现意外或不协调修改，但不能抵御同时改写数据和哈希的攻击者。

网关 `GET /incidents/<incident>/runs/<run>` 返回可下载的 JSON。它通过执行器已认证的只读 `/audit/incidents/<incident>/events?run_id=<run>` 获取动作快照，不直接信任挂载的 JSONL 文件。执行器在同一锁内验证完整审计链，再选择该运行的提案、审批与相关事件。审计不可用或无效时，不提供可信动作状态；证据完整性失败时，不能复用历史绿色观测。

`export_sha256` 覆盖除自身以外的所有字段，序列化使用排序键、UTF-8、非转义 Unicode 和紧凑 JSON 分隔符。`audit_assurance=executor_validated_snapshot` 是服务端在快照时刻的声明；过滤后的导出不能单独认证完整全局链或证明外部锚定。

在 `/console` 选择运行后，只显示该运行的证据、已认证动作、模式、探测结果和导出按钮；隐藏事件级图和工作流，避免混合多个运行。刷新读取已有记录，不重新执行探针。动作回滚后，即使历史成功观测仍在账本中，也不再处于已验证状态。没有运行标识的旧事件仍可在事件汇总中查看。

导出按钮也提供只读 JSON 预览，兼容不自动下载的浏览器。预览保留服务端原始 JSON 文本：JavaScript 重解析会把 `1.0` 变为 `1`，改变 Python 序列化摘要。验证应使用 Python 的 `json.loads`，再执行 `json.dumps(..., sort_keys=True, ensure_ascii=False, separators=(",", ":"))`，不要先经其他序列化器归一化数字。这是第 1 版 Python 序列化摘要，不是 RFC 8785/JCS。

导出明确记录 `agentteams_task=not_attested`、`worker_skill_binding=not_attested`、`model_mode_source=caller_reported`。本实验对服务证据实施运行隔离，尚未提供到原生任务、Worker、Skill 或人员身份的已认证映射。

`approval_mode=automated_lab_harness` 表示脚本通过独立审批凭据批准，证明 API 授权关口和提案绑定，不代表真人决定或模型自主推理。`model_mode=deterministic`、`agentteams_task=false` 均明确记录。响应丢失/重启的验证位于集成测试，不在普通演示轨迹中。

## 执行与复核规则

| 模式 / 来源 | 行为 | 成功的含义 |
| --- | --- | --- |
| `CYBERGUARD_EXECUTION_MODE=simulation`（默认） | 原有演练动作，不修改身份状态 | `simulated_success`；场景恢复标记 `execution=simulated`、`verification_scope=simulated_response_contract` |
| `CYBERGUARD_EXECUTION_MODE=lab` | 仅允许对 `compromised-lab` 执行 `disable_account`，真实修改数据库 | `result=applied` 记录绑定后的后端回执；独立探测前 `verification_status=pending` |
| `scenario_id=lab_identity`、`recovery.metrics` | 读取已认证动作状态，再检查目标与对照账号访问 | 仅当运行/动作/环境匹配、目标已禁用、对照可访问且新回执有效时为 `verified` |
| 通用 `scenario_id=live`、`recovery.metrics` | 输入结论保留为 `reported_verdict` | 有具体独立复核规则前保持 `inconclusive` |

`lab_identity` 目前只支持 `recovery.metrics`，不是完整的新调查场景。请求示例：

```json
{
  "incident_id": "CG-LAB-001",
  "scenario_id": "lab_identity",
  "arguments": {"run_id": "LAB-example", "action_id": "ACT-example"}
}
```

携带网关凭据发送到 `POST /tools/recovery/metrics`。运行未知/不匹配、审计不可用、缺少探测、账号凭据无效、nonce 错误或环境变化返回 `inconclusive`；目标仍可访问或对照账号被禁用返回 `failed`。复核范围为 `point_in_time_lab_access`：两次顺序观测不能证明持续恢复、持久化清除、生产可用性或时间窗口 SLO。

每个实验提案必须有 `run_id`，执行器将目标、环境标识、后端来源和请求绑定到提案记录。`model_mode` 是调用方声明，不是独立模型来源认证；本实验尚未把所有调查、Skill 和 AgentTeams 事件绑定到全局运行清单。

## 故障、重启与并发

修改前，执行器验证审计链，并持久记录 `execution_dispatched`。身份服务在同一 SQLite 事务中提交账号变化和操作回执。HTTP 回执缺失/无效时记录 `execution_unknown`。

发送后再次调用 `execute` 只做状态核对。`POST /actions/<id>/reconcile` 读取已保存的外部回执，可转为 `executed`，不会再次写入。双方使用原数据库、审计目录和凭据重启后仍可核对。回执缺失不能证明操作未送达，因此保持未决，不自动重发或执行取消恢复。

回滚需要审批凭据，记录 `rollback_dispatched`，使用独立持久操作标识。响应丢失进入 `rollback_unknown`，核对后可转为 `rolled_back`。回滚一经发送就将动作移出有效复核集合；关闭的动作不能再次执行。身份服务阻止不同动作/运行回滚他人的操作，重复操作不会再次改变状态。

部署为 **一个执行器进程 / 一个 Uvicorn Worker**。JSONL 审计使用进程内锁，不是分布式事务协调器；能检测记录修改，但没有防止管理员整体删除或替换日志的外部只追加锚点。本适配器的操作数据库提供持久幂等，不提供分布式恰好一次执行、多租户隔离、宿主防篡改或磁盘丢失恢复保证。

## 手动配置服务

`tests/lab_support.py` 是可执行参考，各角色只持有必需凭据：

| 服务 | 配置 / 凭据 |
| --- | --- |
| 身份服务 | `CYBERGUARD_LAB_ADMIN_TOKEN`、`CYBERGUARD_LAB_TARGET_TOKEN`、`CYBERGUARD_LAB_CONTROL_TOKEN`，三个不同的随机值，各至少 32 字符；CLI `--db <path> --port <port>` |
| 执行器 | 原有执行、审批、审计 HMAC 和审计读取密钥；实验管理员 token；`CYBERGUARD_EXECUTION_MODE=lab`；`CYBERGUARD_LAB_URL=http://127.0.0.1:<port>`；独立 `CYBERGUARD_DATA_DIR` |
| 网关 | 原有网关和审计读取 token；目标/对照账号 token；`CYBERGUARD_LAB_URL`；`CYBERGUARD_AUDIT_VERIFY_URL=http://127.0.0.1:<executor-port>`；独立数据目录及场景/知识目录 |

网关不持有实验管理员 token 或审计签名密钥。模型/Worker 不接收审批密钥；手动操作时由人通过 `X-Approval-Secret` 提供审批和回滚凭据。测试框架自动承担该角色以保证可重复。

三个服务均绑定 `127.0.0.1`。客户端拒绝非回环来源和 HTTP 重定向，并绕过系统代理。可作为原生进程或独立 Docker 实验运行，不自动切换基础 Compose 与 AgentTeams 注册。公网暴露或接入真实 IdP 不在本实现范围内。

`deploy/init_secrets.py` 面向 POSIX 部署：发布前以 0600 权限创建密钥，不覆盖已有文件。原生 Windows 无法用 POSIX 权限位建立等价 ACL，故在写入前停止；该部署流程请使用 WSL/Linux。原生账号实验框架不写 `.env`。
