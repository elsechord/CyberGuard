# 单 Agent vs 多 Agent 对比实验 — 2026-09-18

固定规则基线（无 LLM）与真实单 Agent（TokenDance `deepseek-v4.1-flash`，OpenAI 兼容
chat/completions）在 3 个冻结 exercise case 上的量化对比。多 Agent 列由另一组实验填充
（格式已定义，见文末）。本目录含全部原始 run 导出（run-record.json / model-trace.json /
protocol.json / evaluation.json）；不含任何凭据。

## 汇总对比表（多 Agent 待填）

| 指标 | 固定规则基线 | 单 Agent（本文实验） | 多 Agent（原生） |
| --- | --- | --- | --- |
| 样本量 | 3 case × 1（确定性，无随机性） | 3 case × 3 trials = 9 runs | 【待填】 |
| 接受报告完成率 | 3/3 = 100% | 4/9 = 44.4% | 【待填】 |
| 结论全对率（5/5 rubric，按全部 trial） | 3/3 = 100% | 2/9 = 22.2% | 【待填】 |
| 结论全对率（按完成 run） | 3/3 = 100% | 2/4 = 50% | 【待填】 |
| rubric 均分（完成 run） | 5.0 / 5 | 4.25 / 5 | 【待填】 |
| 端到端墙钟（每 run 均值） | < 5 ms（进程内分析） | 24.39 s（17.4–31.2 s，n=9） | 【待填】 |
| prompt tokens（合计 / 均值） | 0 / 0 | 36,492 / 4,054.7 | 【待填】 |
| completion tokens（合计 / 均值，含 reasoning tokens） | 0 / 0 | 47,108 / 5,234.2 | 【待填】 |
| 证据引用合法性（引用 ID ∈ bundle 且 artifact 已采集） | 100%（n=3） | 100%（接受报告由 validator 强制；n=4） | 【待填】 |
| 引用覆盖 ground truth 必需 ID（recall） | 3/3 case = 100% | 4/4 完成 run = 100% | 【待填】 |
| 引用精确率 vs ground truth 最小集 | 1.0（case-001/002/003） | 0.4–0.5（含 GT 外合法引用） | 【待填】 |
| 预算内（20k in / 8k out / 16 calls） | 是（不适用） | 4/4 完成 run within limits | 【待填】 |
| 成本 | 0 | 未知（provider 未提供计费，`cost_usd=null`） | 【待填】 |

注：失败 trial（5/9）也消耗了真实 tokens，已计入上表 token 统计；它们没有可评分报告，
按"未获接受报告"计入完成率与全对率。这是保守口径（failure-counting）。

## 每 case 结果

| Case | 固定规则 | 单 Agent 完成 / 全对 | 单 Agent rubric 分（完成 run） | 单 Agent 均值 tokens (in/out) | 单 Agent 均值墙钟 | 多 Agent |
| --- | --- | --- | --- | --- | --- | --- |
| case-001（可疑持久化） | 5/5 | 2/3 完成，0 全对 | 4/5、3/5 | 4,048.3 / 4,709.0 | 21.63 s | 【待填】 |
| case-002（授权工作负载） | 5/5 | 2/3 完成，2 全对 | 5/5、5/5 | 4,175.3 / 5,787.3 | 27.38 s | 【待填】 |
| case-003（证据缺失场景） | 5/5 | 0/3 完成，0 全对 | 无接受报告 | 3,940.3 / 5,206.3 | 24.16 s | 【待填】 |

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
- **多 Agent 占位格式**：与 single_agent trial 同构——`run-record.json`（mode=multi_agent，
  同 protocol_sha256）+ `evaluate-investigation.py --import-run` 评分；原生 AgentTeams 运行另需
  `scripts/validate-investigation-run.py` 的结构化运行证据（structurally_complete_not_attested）。

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
固定规则基线确定性满足契约但无语义能力。两列都不能代表多 Agent 表现——该列待原生
AgentTeams 实验以同协议填充。

## 文件清单

- `summary.json` — 全部指标（机器可读，与本文数字一致）
- `compute-summary.py` — 指标计算脚本（从本目录 run 导出复算）
- `fixed/case-00X/` — 固定规则 report.json / report.md / evaluation.json
- `single/case-00X/aY/` — 每次单 Agent trial 的 run-record.json / model-trace.json /
  protocol.json /（完成时）evaluation.json
