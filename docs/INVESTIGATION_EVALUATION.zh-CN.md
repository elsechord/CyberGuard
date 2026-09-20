# 证据调查与公平比较

[English](INVESTIGATION_EVALUATION.md) · [中文文档导航](README.zh-CN.md)

本指南介绍可运行的**固定工作流基线**、共享报告格式，以及真实单 Agent / 多 Agent 运行结果的导入接口。基线本身不是自主调查或挖矿检测器；生成格式正确的报告，也不能直接证明模型或 AgentTeams 已运行。

## 运行离线基线

在仓库根目录使用 Python 3.12+，无需额外依赖：

```sh
python scripts/investigate-evidence.py benchmark/investigation/cases/case-001.json --output artifacts/investigation/case-001
python scripts/evaluate-investigation.py benchmark/investigation/cases/case-001.json --rubric benchmark/investigation/evaluator-only/case-001.json --output artifacts/investigation/case-001-evaluation.json
python tests/test_investigation_analysis.py
```

对 case-002、case-003 重复运行。输出包括 `report.json` 和可阅读的 `report.md`。这些命令不调用模型，也不执行建议的处置动作。

| 演练 | 已有观测 | 预期判断 |
| --- | --- | --- |
| case-001 | 高 CPU、临时目录中的可执行路径、匹配的持久化配置 | 提出可疑持久化假设，区分配置存在与调度器实际运行 |
| case-002 | 高 CPU，以及资产负责人的工作负载清单 | 记录清单匹配，不单凭高 CPU 判断攻击，也不宣布主机无风险 |
| case-003 | 高 CPU，持久化信息不可访问，相关认证时间窗缺失 | 保持工作负载性质未决，请求缺失观测，避免破坏性处置 |

这些材料是构造的演练样本，不是真实挖矿流量或独立现场验证案例。每个证据包明确标记 `provenance.kind=exercise`。

## 输入与固定规则

共享证据模块验证各产物 SHA-256 和整个证据包 SHA-256。哈希发现字节变化，不认证作者或观测真实性。

基线把至少 40% 的 CPU 采样与持久化命令中相同的绝对可执行路径关联。位于 `/tmp`、`/var/tmp`、`/dev/shm` 的路径增加可疑位置线索。明确禁用的持久化项不作为正向支持；`enabled=null` 表示调度器状态尚未确认。规则不依赖演练文件名、PID、程序名称、端口、`malicious` 标签或评测答案。

为避免泄露秘密，默认不采集解释器参数，因此解释器启动的脚本可能无法匹配其可执行路径。低 CPU、内存驻留、盗用账号等入侵不在该规则覆盖范围内。配置不能证明实际由哪个父进程启动，CPU 本身不能证明挖矿；提供的资产清单是待审查的反证，不是二进制真实性认证。

认证/网络观测仍可供模型或人工调查员使用，但固定规则不把任意日志文本解析成初始入侵判断。入口和组织归因保持未决，缺失产物不转换为反向证据。

## 报告格式与信任范围

`cyberguard_investigation.analysis.analyze_bundle(bundle, run_id=None)` 返回：

```json
{
  "schema": "cyberguard-investigation-report/v1",
  "bundle_id": "...",
  "bundle_sha256": "...",
  "mode": "fixed_workflow",
  "findings": [{
    "finding_type": "suspicious_persistence",
    "claim": "A specific, bounded claim",
    "status": "supported",
    "supporting_evidence_ids": ["EV-..."],
    "contradicting_evidence_ids": [],
    "limitations": ["Why this does not establish malware identity"]
  }],
  "unknowns": ["Initial access vector"],
  "next_collection": ["Request the missing incident-window logs"],
  "proposed_actions": [{
    "action": "review_persistence_and_preserve_binary",
    "target": "/example/path",
    "reason": "Review correlated observations before containment",
    "evidence_ids": ["EV-..."],
    "requires_approval": true
  }]
}
```

`mode` 也允许 `single_agent`、`multi_agent`。便携报告中的 `run_id` 可选，但网关必须将报告绑定到自身管理的不可变运行。报告不能自行授权执行或更改运行模式。

`report.validate_report(report, bundle, expected_mode=...)` 对以下情况抛出 `ValueError`：证据包 ID/哈希或模式不匹配，引用未知/不可用，supported 结论缺少支持，refuted 结论缺少反证，或动作无需审批。inconclusive 结论应解释限制。同一产物可同时包含支持和反驳观测，仍需判断其含义。格式校验不能验证结论真伪或引用是否足以推出结论；即使证据 ID 正确，模型也可能写出无依据内容，因此需要语义审阅。

## 比较协议与真实运行导入

调用任何模型**之前**生成协议：

```sh
python scripts/evaluate-investigation.py benchmark/investigation/cases/case-001.json --protocol-only --output artifacts/investigation/case-001-protocol.json
```

协议绑定精确证据哈希、相同任务、`read_evidence_bundle` / `submit_investigation_report` 工具、只读权限，以及共享输入/输出 token 和工具调用上限。默认上限为 20,000 输入 token、8,000 输出 token、16 次工具调用，统计多 Agent 运行中**所有角色**及重试的总量。这些是比较设置，不能据此宣称运行时已经强制执行。未知费用、时间和 token 填 `null`，不填零；固定工作流不使用模型 token。

模型运行记录的导入格式：

```json
{
  "mode": "single_agent",
  "status": "completed",
  "bundle_id": "copy from protocol",
  "bundle_sha256": "copy from protocol",
  "protocol_sha256": "copy from protocol",
  "report": {},
  "usage": {
    "input_tokens": null,
    "output_tokens": null,
    "tool_calls": null,
    "elapsed_seconds": null,
    "cost_usd": null
  },
  "execution_evidence": "location and digest of actual runtime receipts"
}
```

将 `report` 替换为完整的证据绑定报告。以上仅为格式示意，不是完成记录。使用 `--import-run FILE` 导入，可重复指定另一模式。`evaluation.validate_run_record` 拒绝变更后的证据包/协议/模式及无效用量。超预算记录保留并标为 `exceeded`，缺少测量为 `unknown`。在核验运行证据之前，外部回执元数据仍标记 `caller_reported_not_independently_attested`；单独一份导入 JSON 不能证明模型实际执行。

没有导入时，单 Agent 和多 Agent 结果为 `not_run`，不生成分数或用量，也不能宣布比较胜者。

## 将答案与被评测 Agent 隔离

只通过只读工具提供案件证据包，不向被评测 Agent 提供仓库 shell、评测器目录、答案表、演练生成器、固定流程报告或其他运行输出。

`benchmark/investigation/evaluator-only/` 保存独立预期观测，`build_exercises.py` 仅供维护者生成样本；两者不应进入 Agent 镜像或可访问挂载。隔离必须由运行器落实，目录名称本身不是访问控制。演练源码公开，因此这三个案例不能证明盲测泛化；比较有效性前需构建新的保留案例，并由独立人员审阅。

当前评分器检查结论类型/状态、必需引用 ID、是否擅自断言入口/攻击者，以及是否提出不当状态变更建议。通过数是小规模格式与行为评分，不是调查准确率，无法判断自然语言推理是否充分。现场评测还需要独立语义审阅、更多案例、误报/遗漏指标、真实 token/费用/时间回执和人工审阅耗时。单 Agent 应获得相同工具与权限，不能通过人为限制它的操作制造多 Agent 优势。

## 真实单模型运行器（非 AgentTeams）

`scripts/run-investigation-model.py` 发起真实 OpenAI 兼容 Chat Completions 请求，并执行模型选择的工具循环。只允许 `read_evidence_bundle`、`submit_investigation_report`：前者提供证据包，后者按同一证据包与 `mode=single_agent` 校验完整报告。模型无法使用 shell、网页、文件系统搜索、处置执行或评测器工具；运行器不导入固定规则分析器或预期答案。

初始实验只接受演练证据包。来源为 `live_collection` 或 `import` 时，在任何网络调用前拒绝。

```sh
python scripts/run-investigation-model.py \
  --bundle benchmark/investigation/cases/case-001.json \
  --output artifacts/live-single/case-001 \
  --endpoint https://YOUR-EXPLICIT-ENDPOINT/v1/chat/completions \
  --model YOUR-MODEL \
  --env-file /secure/location/model.env
```

环境文件仅按值解析，不执行内容。接受 `CYBERGUARD_MODEL_API_KEY`、`AGENTTEAMS_LLM_API_KEY` 或 `OPENAI_API_KEY`，文件应置于仓库外并限制权限。显式 HTTPS endpoint 在本轮固定，模型文本无法改变；拒绝嵌入凭据、查询字符串和重定向。错误响应不复制到日志；若提供商回显已知凭据，保存产物前会移除。

默认两个函数在本地执行，轨迹标记 `local_allowlisted_functions_not_agentteams`。使用已有网关运行时，传入 `--gateway-url http://127.0.0.1:PORT --run-id RUN`，并在模型上下文之外提供不同的 `CYBERGUARD_API_TOKEN`、`CYBERGUARD_REPORT_TOKEN`。先单独创建/导入证据包和不可变单 Agent 运行，运行器不持有导入凭据。网关证据须与本地证据包完全一致；HTTP 调用使用真实读取/报告 API，保留回执。本地函数基线与 AgentTeams 是不同运行时，工具语义相同不能消除这一比较变量。

每个阶段保存 `run-record.json`、`protocol.json`、`model-trace.json`。轨迹保留请求、提供商原始响应及 usage、assistant 消息、工具参数和结果，仅脱敏凭据，不记录 Authorization 头。运行声明是本地观测而非独立认证；提供商 usage 不等于实付账单，因此费用记为 `null`。

Token 汇总每次请求的 `prompt_tokens` / `completion_tokens`，包括报告修复失败的尝试。输入预检使用序列化 UTF-8 字节数的保守界限，`max_tokens` 不超过剩余输出预算。字节界限不是模型分词器保证，提供商报告超限时会记录并停止；缺少 usage 时不继续请求，不虚构零消耗。工具尝试共享 16 次预算，每轮不重置。最多 12 次迭代，响应上限 1 MiB，报告上限 256 KiB。传输失败、输出畸形或预算耗尽产生真实失败记录，不替换为预设报告。

只有完成记录可通过 `--import-run` 导入评测。判断单/多 Agent 效果前，应审阅真实执行、语义充分性、试验次数与运行时差异。

### 运行完整性与重复尝试

HTTP 运行器在首次模型请求前，通过只读报告端点读取已有网关运行元数据，不消耗工具配额。校验运行哈希、ID、single-agent 模式、证据 ID/哈希、共同预算与工具范围。网关运行必须尚无报告或工具用量。后续读取回执验证哈希、运行、证据、角色、序号和工具；提交确认必须包含原样报告、预期报告 ID、匹配的运行/回执哈希、有效引用状态与 `actions_executed=false`，不能只看 HTTP 200。

每次本地调用先在当前系统用户的 `~/.local/state/cyberguard/model-attempts.sqlite` 中原子登记运行 ID，失败或进程退出后保留。即使换输出目录也不能复用运行 ID；重试必须使用新尝试/运行 ID，既有费用仍计入整体实验。默认随机运行 ID 明确区分新尝试，不重置旧账本。测试可通过 Python API 提供隔离账本路径，CLI 不开放该覆盖参数。

SQLite 登记只对共享该系统用户账本的运行器保证原子性；网关元数据检查不是分布式原子认领。不要从另一主机、系统用户或独立账本并发使用同一网关运行。可信操作员可以删除账本或换 ID，因此这是本地原型计量，不是抗对抗的全局花费上限；新尝试的 token 仍应计入总成本。

严格 JSON 校验检查整棵树中的有限数值，包括 `1e999` 等指数溢出以及未知字段。运行器拒绝报告顶层和嵌套格式外字段，避免无效提供商响应破坏最终 JSON 序列化并让状态滞留 running。凭据脱敏在 JSON 编码前遍历字符串值和键，引号或反斜杠不能绕过。

原子文件写入遇到短暂 `PermissionError` 最多重试三次，间隔 25/50 ms，以适应 Windows 短暂文件锁。只重试文件 I/O，不重试模型或工具请求。持续失败返回 `artifact_persistence_failed`，明确提示最终记录可能未落盘，不报告为持久完成。
