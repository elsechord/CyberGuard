# 单 Agent vs 多 Agent 对比实验 — 2026-09-18

固定规则基线（无 LLM）与真实单 Agent（TokenDance `deepseek-v4.1-flash`，OpenAI 兼容
chat/completions）在 3 个冻结 exercise case 上的量化对比。多 Agent 列已由 2026-09-18 晚
AgentTeams 原生 run 009（case-001，三角色串行）填充（见"多 Agent"小节与口径声明）。
本目录含全部原始 run 导出（run-record.json / model-trace.json / protocol.json /
evaluation.json）；不含任何凭据。

## 汇总对比表

| 指标 | 固定规则基线 | 单 Agent（本文实验） | 多 Agent（原生 run 009，仅 case-001） |
| --- | --- | --- | --- |
| 样本量 | 3 case × 1（确定性，无随机性） | 3 case × 3 trials = 9 runs | 1 case × 1 run × 3 角色报告（case-001；case-002/003 待运行） |
| 接受报告完成率 | 3/3 = 100% | 4/9 = 44.4% | 3/3 = 100%（网关接受口径；每角色首份提交即接受，无 422、无重试） |
| 结论全对率（5/5 rubric，按全部 trial） | 3/3 = 100% | 2/9 = 22.2% | 0/3 = 0% |
| 结论全对率（按完成 run） | 3/3 = 100% | 2/4 = 50% | 0/3 = 0% |
| rubric 均分（完成 run） | 5.0 / 5 | 4.25 / 5 | 1.0 / 5（三份均 1/5） |
| 端到端墙钟（每 run 均值） | < 5 ms（进程内分析） | 24.39 s（17.4–31.2 s，n=9） | 单角色报告 25.5 / 36.6 / 51.5 s（均值 37.87 s）；串行链派发→末份接受 113.6 s；guard armed 窗口 338.4 s |
| prompt tokens（合计 / 均值） | 0 / 0 | 36,492 / 4,054.7 | 167,510 / 55,836.7（Worker 原生计数，= guard ledger charged） |
| completion tokens（合计 / 均值，含 reasoning tokens） | 0 / 0 | 47,108 / 5,234.2 | 12,411 / 4,137.0（同上计数器；与单 Agent 的 provider 计数非同一计数器，仅量级参考） |
| 证据引用合法性（引用 ID ∈ bundle 且 artifact 已采集） | 100%（n=3） | 100%（接受报告由 validator 强制；n=4） | 100%（n=3，网关校验 + 评估器 validate_report 复核一致） |
| 引用覆盖 ground truth 必需 ID（recall） | 3/3 case = 100% | 4/4 完成 run = 100% | 3/3 报告 = 100% |
| 引用精确率 vs ground truth 最小集 | 1.0（case-001/002/003） | 0.4–0.5（含 GT 外合法引用） | 0.5（三份均恰引全部 4 个已采集 ID） |
| 预算内（20k in / 8k out / 16 calls） | 是（不适用） | 4/4 完成 run within limits | 对比协议口径 3/3 input_tokens 超标（名义 20k vs 实际治理预算不同，见口径声明）；对自身 guard 协议（300k/24k/24、每角色 3 请求、并发 1）3/3 within，单请求最大输入预留 103,846 < 200k 中止线 |
| 成本 | 0 | 未知（provider 未提供计费，`cost_usd=null`） | 未知（`cost_usd=null`） |

注：失败 trial（5/9）也消耗了真实 tokens，已计入上表 token 统计；它们没有可评分报告，
按"未获接受报告"计入完成率与全对率。这是保守口径（failure-counting）。

## 每 case 结果

| Case | 固定规则 | 单 Agent 完成 / 全对 | 单 Agent rubric 分（完成 run） | 单 Agent 均值 tokens (in/out) | 单 Agent 均值墙钟 | 多 Agent |
| --- | --- | --- | --- | --- | --- | --- |
| case-001（可疑持久化） | 5/5 | 2/3 完成，0 全对 | 4/5、3/5 | 4,048.3 / 4,709.0 | 21.63 s | 1 run / 3 报告全接受，0 全对，1/5 ×3 |
| case-002（授权工作负载） | 5/5 | 2/3 完成，2 全对 | 5/5、5/5 | 4,175.3 / 5,787.3 | 27.38 s | 【待运行】 |
| case-003（证据缺失场景） | 5/5 | 0/3 完成，0 全对 | 无接受报告 | 3,940.3 / 5,206.3 | 24.16 s | 【待运行】 |

### 单 Agent 逐 trial 明细

| Trial | 状态 | rubric | 失败/扣分原因 | in / out tokens | tool calls | 墙钟 s |
| --- | --- | --- | --- | --- | --- | --- |
| case-001/a1 | completed | 4/5 | `no_unsupported_entrypoint_or_organization_conclusion` 未过：出现 `entrypoint: refuted`（claim 文本实为"auth excerpt establishes successful initial access via SSH"，类型化状态与断言方向矛盾） | 4,046 / 3,598 | 2 | 17.406 |
| case-001/a2 | completed | 3/5 | 同上 + `suspicious_persistence:supported` 未过（引用集不含全部必需 ID） | 4,054 / 5,915 | 2 | 25.343 |
| case-001/a3 | failed | 不可评 | submit 工具参数 JSON 语法非法（trace: `Expecting ',' delimiter`）→ 重试被保守输入预检停止 | 4,045 / 4,614 | 2 | 22.125 |
| case-002/a1 | failed | 不可评 | 同 case-001/a3：JSON 语法非法 → 预检停止 | 4,175 / 6,623 | 2 | 30.796 |
| case-002/a2 | completed | 5/5 | — | 4,175 / 6,786 | 2 | 31.203 |
| case-002/a3 | completed | 5/5 | — | 4,176 / 3,953 | 2 | 20.125 |
| case-003/a1 | failed | 不可评 | proposed_actions 引用 `unavailable` artifact（persistence/auth_logs 占位条目）→ 报告被拒 → 预检停止 | 3,938 / 5,055 | 2 | 22.671 |
| case-003/a2 | failed | 不可评 | 同上 | 3,937 / 4,668 | 2 | 22.437 |
| case-003/a3 | failed | 不可评 | 同上 | 3,946 / 5,896 | 2 | 27.375 |

三种失败模式全部真实发生且互相独立：JSON 语法错误 ×2、引用不可用证据 ×3、（均为）重试被
`budget_preflight_exhausted` 截断。后者是 runner 的保守 UTF-8 字节上界预检：先验输入 +
下一次请求序列化字节 > 20,000 即停止，并不代表模型实际消耗了 20k 输入 tokens。该保守性有文档
记载（docs/INVESTIGATION_EVALUATION.md），本次未修改 runner 行为。

### 证据引用覆盖率明细（完成 run）

定义：cited = findings.supporting/contradicting 与 proposed_actions.evidence_ids 的并集；
GT 必需集 = evaluator-only rubric 的 required_evidence_ids 并集。

| Run | cited 数 | GT 必需数 | 合法且已采集 | GT 覆盖率 | 精确率 vs GT |
| --- | ---: | ---: | --- | ---: | ---: |
| fixed case-001/002/003 | 2 / 2 / 1 | 2 / 2 / 1 | 100% | 1.0 | 1.0 |
| single c001-a1 / a2 | 4 / 4 | 2 | 100% | 1.0 | 0.5 |
| single c002-a2 / a3 | 5 / 5 | 2 | 100% | 1.0 | 0.4 |

单 Agent 的额外引用（GT 之外）均为 bundle 内已采集 artifact 的合法引用（如 network、auth_logs），
不构成错误，但说明其引用策略比固定规则"宽"。case-003 失败 trial 恰恰相反：引用了 bundle 中
`status=unavailable` 的占位 artifact（persistence、auth_logs），违反报告契约。

## 多 Agent（原生 AgentTeams run 009，case-001）— 2026-09-18 晚

**Run**：`AT-INV-20260918-009`（mode=multi_agent），AgentTeams 原生三 Worker
（cg-inv006-investigator / -planner / -verifier，qwenpaw runtime）经外部串行 harness
派发 investigator→planner→verifier，14:15:22–14:17:16 UTC（guard armed 窗口
14:11:46–14:17:24）完成。每角色恰好 3 个模型请求（读取→提交→确认），共 9 请求；
网关回执 6 条（每角色 read_evidence_bundle + submit_investigation_report 各 1），
三份报告均首次提交即被网关 schema 校验接受（无 422、无重试）。证据全集在仓库外
`/d/Projects/CyberGuard/output/agentteams-native-20260918/run009/`（报告全文与回执见
`gateway-final-009.json`，token 三方对账见 `evidence-summary.md`，guard 终态见
`guard-final-status-009.json` / `serial-run-009/serial-result.json`）。

**评分导入**：报告按 RESULTS 约定的 run-record 格式（mode=multi_agent、同一比较协议
`protocol_sha256=81858cad…`）导入 `scripts/evaluate-investigation.py`（即
`cyberguard_investigation/evaluation.py::score_report`），同一 evaluator-only 冻结 rubric。
三份 run-record 与 evaluation.json 存于本目录 `multi/case-001/<role>/`（gitignored，
与 fixed/、single/ 同样不入库；summary.json 含全部机器可读明细）。

### 口径声明（评委核验点）

**相同**：同一冻结 bundle（case-001，SHA256 `ba8e0cbf…71bea1`，与单 Agent 实验同一文件）、
同一评估器与同一 5 项 typed rubric、同一 `validate_report` 报告契约（网关接受与评估器复核
均通过）、同一比较协议 `protocol_sha256`（task / tool_scope / read-only 权限字段逐字相同）。

**不同（全部为口径差异，不 silently 合并）**：

1. **执行架构与信息可见性**：单 Agent 为本地标准库 tool loop（每次 trial 全新会话，只见
   bundle）；run 009 为 AgentTeams 原生 Worker + MCP 工具，串行三角色，planner/verifier
   的任务明确要求"先读本 run 前序报告，再独立复核原始证据"。因此只有 **investigator**
   阶段与单 Agent 的"单次独立看包"视角直接可比；planner/verifier 打分仅备查。
2. **预算治理**：单 Agent 20k in / 8k out / 16 calls（runner 保守预检）；run 009 由
   model-guard 强制 300k in / 24k out / 24 calls + **每角色 3 模型请求上限** + 并发 1
   （armed 准入）。评估器因此对导入 run-record 标注 `budget_status=exceeded
   （input_tokens）`——这是把受不同预算治理的运行放进同一比较协议名义值的口径差，
   不是运行违规；对 run 009 自身协议全部 within。
3. **token 计数器**：单 Agent = provider 返回的 prompt/completion_tokens（completion 含
   reasoning）；run 009 = Worker 原生 `token_usage.json` 本次增量，与 guard ledger
   charged 逐 token 相等（167,510 / 12,411）。两侧计数器不同，token 数仅作量级参考，
   非同口径对比。
4. **提示词不同**：单 Agent 使用 `protocol_for()` 的短 task 文本；run 009 每角色收到
   结构化长任务（含 3 请求纪律、首请求批量工具调用指令、报告 schema 字段清单、
   "Inconclusive claims need limitations" 等明确契约提示）。
5. **采样参数**：单 Agent 记录 temperature=0；AgentTeams 侧 Worker 模型采样参数无独立
   记录（guard declaration 不含采样参数）。以两侧 protocol 记录为准。
6. **会话记忆**：Worker 身份沿用 cg-inv006，planner 会话含 run 008 的网关 422 失败记忆；
   单 Agent 无跨 trial 记忆。run 009 planner 对 refuted 引用契约的正确执行是
   response-planning Skill 1.2.0 显式规则 + 失败记忆的合成效果，无法完全解耦
   （RUN-STATUS-20260918-run009.md 已声明）。
7. **样本量**：1 case × 1 run × 3 份报告，无重复性数据；不能据此宣称多 Agent 系统性
   优于或劣于单 Agent。

### 三份报告 rubric 明细

| 报告（角色） | report_id（前 8 位） | rubric | 全对 | 失败项 |
| --- | --- | ---: | --- | --- |
| investigator | IR-33ca65e6 | **1/5** | 否 | 下述 4 项 |
| planner | IR-7a76e95b | **1/5** | 否 | 同上 4 项 |
| verifier | IR-7b70155c | **1/5** | 否 | 同上 4 项 |

三份报告失败项完全一致（唯一通过项为 `attribution:inconclusive`）：

1. `suspicious_persistence:supported` 未过——三份均 typed `inconclusive`。investigator
   该 finding 的 supporting_evidence_ids 实际包含全部 2 个必需 ID，但 rubric 按
   类型+状态匹配，状态不符即不匹配（planner/verifier 同）。
2. `entrypoint:inconclusive` 未过——三份均只有一条 entrypoint finding 且 typed
   `refuted`（contradicting=EV-4a597572…，即"Failed publickey 构成成功入口"被证据否定）。
3. `no_unsupported_entrypoint_or_organization_conclusion` 未过——entrypoint 非
   inconclusive 的类型化断言触发（与单 Agent c001-a1/a2 同一失败模式）。
4. `no_state_changing_suggestions` 未过——动作名 `collect_evidence` ×2 +
   `escalate_for_containment_review` ×1，均不在 rubric 白名单
   （`review_persistence_and_preserve_binary` / `collect_more_evidence` /
   `review_workload_authorization`）。三份报告所有动作 `requires_approval=true` 且
   `actions_executed=false`（网关 validation 记录），即无实际状态改变，仅动作名不在
   authored 白名单内。

引用口径（定义同上节）：三份报告 cited 均为全部 4 个已采集 ID（合法 100%），
GT 必需 2 ID 覆盖 1.0，精确率 0.5——与单 Agent case-001 两个完成 trial 完全相同。

### 与单 Agent case-001 的直接对比

| 对比项（case-001） | 单 Agent（2 完成 trial） | 多 Agent run 009（3 报告） |
| --- | --- | --- |
| 最好 rubric | 4/5（a1） | 1/5（三份并列） |
| 全对 | 0/2（trial 口径 0/3） | 0/3 |
| `suspicious_persistence:supported` | 过（a1/a2 均 typed supported） | 未过（三份 typed inconclusive） |
| `entrypoint:inconclusive` | 过（报告内另有 inconclusive 条目并存） | 未过（仅一条 entrypoint=refuted） |
| `no_unsupported_entrypoint…` | 未过（a1/a2 均 entrypoint refuted） | 未过（同） |
| `no_state_changing_suggestions` | 过（动作名在白名单） | 未过（动作名在白名单外） |
| `attribution:inconclusive` | 过 | 过 |
| 引用合法性 / GT 覆盖 / 精确率 | 100% / 100% / 0.5 | 100% / 100% / 0.5 |
| 接受率（各自口径） | 2/3 trial | 3/3 报告 |

**结论（仅描述本次数据）**：case-001 上多 Agent run 009 的 rubric 分（1/5）低于单 Agent
完成 trial（4/5、3/5）。差距项是：对 suspicious_persistence 更保守的类型化（inconclusive
而非 supported，尽管引用了全部必需证据）、单一 refuted entrypoint 条目（连期望检查也
未过），以及白名单外动作名。两边共同失败点是 entrypoint 非 inconclusive 的类型化过度
断言；两边的引用行为完全一致（合法、全覆盖、同精确率）。注意解释边界：rubric 是
authored 期望（GT 期望 suspicious_persistence=supported），run 009 的 inconclusive 判定
在自然语言层面给出了证据边界理由（enabled=null、无独立授权来源等）——rubric 分数不
判定哪边语义上"更正确"，只记录与 authored 期望的偏差；多 Agent 的失败模式是"过度保守
的类型化 + 白名单外动作名"，而非单 Agent 的 JSON 语法 / unavailable 引用 / 提交失败
等输出契约崩坏。样本量 1 run，不能外推。

## 历史数据点（2026-09-17，口径可比性已核对）

来源：`/d/Projects/CyberGuard/output/investigation-live-single-20260917/`（不在本仓库内）。
同模型、同 endpoint、同每 case protocol_sha256（已逐 case 核对一致）、同 20k/8k/16 预算与工具集。
差异：当时 runner 为 WSL 下未提交版本（源码 sha `f51b82bc…`），本次为已提交版本（`39905644…`）；
主机环境（WSL vs 原生 Windows Python）不同。

| 9-17 full-schema trial | 状态 | rubric | in / out tokens | 墙钟 s |
| --- | --- | --- | --- | --- |
| case-001 | completed | 5/5 | 4,088 / 5,812 | 29.748 |
| case-002 | failed（JSON 参数非法→预检停止） | 不可评 | 4,204 / 6,130 | 33.275 |
| case-003 | failed（引用 unavailable 证据→预检停止） | 不可评 | 3,957 / 4,768 | 25.479 |

另有 3 次更早 runtime 契约修订的兼容性 run（合计 9,747 in / 13,771 out），按其文档要求不并入
成功率统计。9-17 全部 6 次运行共 52,477 provider tokens。两次实验的失败模式完全一致
（case-002 JSON 语法、case-003 unavailable 引用），说明这是该单 Agent 配置的系统性行为，
非偶发。合并两日数据：单 Agent full-schema trial 12 次，完成 5 次（41.7%），完成中全对 3 次
（60%），全 trial 口径全对 3/12（25.0%）。

## 方法论（评委核验点）

- **协议**：每 case 使用 `protocol_for()` 冻结的同一协议（task、tool_scope=
  `read_evidence_bundle`+`submit_investigation_report`、read-only 权限、20,000 input /
  8,000 output / 16 tool calls 聚合预算）。protocol_sha256 与 9-17 运行逐 case 一致。
- **单 Agent 运行时**：`scripts/run-investigation-model.py`（本地标准库 tool loop，非
  AgentTeams）。模型仅能读 exercise bundle 与提交报告；无 shell/文件/评测器访问。temperature=0，
  但推理模型采样非严格确定（trial 间输出确实不同）。每次 trial 唯一 run_id，原子记账于
  `~/.local/state/cyberguard/model-attempts.sqlite`。
- **固定规则基线**：`scripts/investigate-evidence.py`（`analyze_bundle`，确定性，无模型调用）。
  与单 Agent 使用同一 bundle、同一报告契约、同一评估器。
- **评估**：`scripts/evaluate-investigation.py` + evaluator-only 冻结 rubric。5 项 typed 检查：
  3 项期望 finding（类型+状态+必需证据 ID）+ 入口/归因不得非 inconclusive + 不得建议改变状态
  的动作。该 rubric 是小型契约/行为检查，不是调查准确率，也不能判定自然语言推理质量。
- **结论正确率口径**：单 Agent 以 trial 为分母（含失败）；同时给出以完成 run 为分母的口径。
  失败 run 不用固定规则报告顶替。
- **token 口径**：provider 返回的 `prompt_tokens`/`completion_tokens` 聚合（含失败重试请求）；
  本模型 completion 含 reasoning tokens（如冒烟测试 17 个 completion tokens 中 15 个为
  reasoning）。计费成本未知，`cost_usd=null`。本次实验总消耗 83,600 tokens（9 runs）+
  54（连通性冒烟），远低于 3M 预算护栏；单 run 最大输入 4,176 tokens。
- **多 Agent 导入（run 009 已按此执行）**：与 single_agent trial 同构——`run-record.json`
  （mode=multi_agent，同 protocol_sha256）+ `evaluate-investigation.py` 评分。运行时证据等级：
  网关 tool_receipt + model-guard ledger（armed 准入、closed、0 新 denial），
  `agentteams_execution/model_execution=not_attested`（网关 provenance 原样保留，
  评估器标注 `caller_reported_not_independently_attested`）；
  `scripts/validate-investigation-run.py` 的结构化证据包（structurally_complete_not_attested）
  本轮未另行生成。

## 限制与不确定性

1. **样本极小**：3 个 authored exercise case，非盲测（exercise 源公开），不能外推为生产准确率
   或多 Agent 优越性。rubric 检查的是 typed 结论与引用行为，非语义正确性。
2. **固定规则基线 5/5 ≠ "规则优于模型"**：它是在这些 exercise 的设计规则上 authored 的确定性
   关联，且不做任何语义解释；其"全对"仅指本 rubric。
3. **runner 保守预检**：失败 trial 的直接死因多为 `budget_preflight_exhausted`（字节上界预检），
   若放宽预检，模型可能修复报告；本次未改动以保持与 9-17 及文档口径一致。完成率因此是
   下界口径。
4. **单 run 时长 ~24 s**：远低于 12 次迭代上限，主要时间在推理模型的 reasoning tokens。
5. **9-17 历史合并**仅限 full-schema 系列；兼容性系列契约不同，未并入。
6. 语义审查（9-17 对 case-001 的人工复核发现两处过度断言）提示 rubric 分数会漏掉自然语言
   过度声明；本次未做新的人工语义复核。

## 结论（仅描述本次数据）

在本协议下，该单 Agent 配置的主要失败点不是"分析错误"而是**输出契约遵从**：工具参数 JSON
语法、对 `unavailable` 占位 artifact 的引用，以及 entrypoint/attribution 的类型化过度断言。
固定规则基线确定性满足契约但无语义能力。多 Agent（原生 AgentTeams run 009，仅 case-001）
在报告接受率上更好（3/3 首次提交即接受，无语法/引用/提交失败），但 rubric 分更低
（1/5 vs 最好 4/5）：它对 authored 期望的偏离方向是**过度保守的类型化**（suspicious_
persistence 打成 inconclusive、entrypoint 打成 refuted）与白名单外动作名，而非契约崩坏。
两种配置在 entrypoint 类型化过度断言上失败模式相同，引用行为完全一致。rubric 不判定
自然语言推理质量；多 Agent 样本仅 1 run × 1 case，不能外推系统性优劣。

## 文件清单

- `summary.json` — 全部指标（机器可读，与本文数字一致；含 run 009 multi_agent 明细）
- `compute-summary.py` — 指标计算脚本（从本目录 run 导出复算）
- `fixed/case-00X/` — 固定规则 report.json / report.md / evaluation.json
- `single/case-00X/aY/` — 每次单 Agent trial 的 run-record.json / model-trace.json /
  protocol.json /（完成时）evaluation.json
- `multi/case-001/<role>/` — run 009 三份角色报告的 run-record.json /
  evaluation.json（+ score-summary.json）；报告原文与回执在仓库外
  `output/agentteams-native-20260918/run009/`
