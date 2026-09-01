# CyberGuard GOAI 复赛行动计划（2026-09-01 更新）

> 目标：9.3 复赛提交截止 + **9.4 线上答辩（第 5 组第 23 队，15:28—15:36，15:18 前候场，钉钉会议）**。
>
> **✅ 评委点名的核心缺口已补齐（2026-08-29）。** 真实 WebShell 任务（CG-2026-0002）已在 AgentTeams v1.2.2 + cyberguard-soc 团队（7 Worker 全员 Running）上从创建跑到终态：调查（含两次提示注入抵抗）→ 规划 → 4 条 L2 动作人工审批（审批人 shuuyou，哈希绑定）→ 执行 → 独立复测第一轮 inconclusive（契约检出 target 不精确，异常分支重开）→ 补充提案再审再执行 → verdict=verified → 结案报告 → 回滚演示（复测回落 inconclusive）。证据包：`/srv/cyberguard/artifacts/live-task/webshell-20260828T163202Z/`（含 tar.gz + SHA256SUMS + evidence-manifest.json）。readiness 闸门 valid=true。

## 0. 9.1 新规同步（复赛参赛指南 + 群通知）

与之前手册/邮件相比的变化点：

- **答辩不设单独分值**：按已公布评审维度（场景价值 25% / 协同闭环 25% / Skill 工程 25% / 工程落地与安全可审计 20% / 开源 5%）结合"作品完成度+答辩呈现"整体评分。
- **答辩结构 8 分钟**：项目陈述 3 分钟 + **Demo 演示仅 1 分钟** + 问答 3 分钟 + 切换 1 分钟。超时风险高，陈述与 Demo 必须彩排到秒。
- **Demo 材料双版本**：提交的 Demo 视频 ≤8 分钟（须含 Agent 协作过程、Skill 调用证据、异常处理演示）；答辩现场 Demo 仅 1 分钟，需剪精华版。
- **更新版方案 PPT 必须"标红呈现初赛反馈的具体调整点"**，并提供场景闭环图、审批/回滚/审计流程、跨行业迁移路径。
- **硬性纪律**：队长或正式队员本人答辩（身份核验，替答取消资格）；会议昵称"答辩序号+真实姓名+队伍名"（我们：23号+姓名+队名）；候场 15:18 前入场；答辩全程云录制；会议信息禁止外传；提前一天完成音视频/屏幕共享/Demo 彩排。
- 钉钉评审维度文档需登录，未抓取；以 PDF 指南 + 初赛手册评审标准为准。

## 1. 评委反馈解读（初赛邮件，已闭环）

原话（赛道一邮件）：

> 优点是审批哈希绑定、最小权限、独立复测和回滚组成的安全工程闭环；缺点是**缺少一条真实 AgentTeams 原生任务从创建到终态的完整运行证据**。可以用现有 WebShell 场景跑通并封装一份"单个真实 AgentTeams Task 证据包"，至少包含**原生任务事件链、审批、执行、独立复测、异常恢复和终态**。

翻译成一个检查单，证据包必须含：

| # | 评委要的 | 对应产物 |
|---|----------|----------|
| 1 | 原生任务事件链 | Matrix 房间全量事件导出（`matrix-events.jsonl`），从任务创建消息到终态报告，含 event_id/时间戳/发送者 |
| 2 | 审批 | L2 动作的人工审批记录（`approval-*.json`，含 `proposal_record_sha256` 哈希绑定、approver、有效期） |
| 3 | 执行 | 执行回执（`execution-*.json`）+ 审计链（HMAC 链式 record） |
| 4 | 独立复测 | recovery-verifier 独立查询的恢复证据（`recovery.metrics` verdict=verified，数据源是 executor 认证审计状态而非 Agent 自述） |
| 5 | 异常恢复 | 回滚一个已执行动作 → 复测 verdict 回到 inconclusive（`rollback.json` + `post-rollback-recovery.json`）；另有场景内置的提示注入标记抵抗（`CYBERGUARD_INJECTION_MARKER` 不得出现在任何 Agent 输出） |
| 6 | 终态 | 事故终态 JSON + 证据索引 + 审计 checkpoint（HMAC 签名）+ 中文事故报告 |

**这正好补上了仓库自己承认的缺口**（`docs/COMPETITION.md` 把 "AgentTeams Matrix trace" 列为 TODO；现有 judge-demo 是纯 curl 确定性演示，不过 LLM/AgentTeams）。

## 2. 环境现状与今日进展

- 容器（armaygooser-desktop）里有 v0.11.0 部署 + 8 月 15 日确定性 demo 证据（两场景 12 项断言全过），但 **Manager bootstrap 停在第 1 步**：两个工具服务从未注册进 Higress（`manager-result.json: "needs_human_tool_registration"`），Team 从未创建，没有任何真实任务运行记录。
- GitHub 仓库已是 v0.12.0（技能/文档更新，服务代码与 v0.11.0 相同）。**复赛提交应以 v0.12.0 + 本次证据包为准。**
- 容器内 DeepSeek API key、admin 密码均已在 `agentteams.env` 配好，可直接复用。
- **8.28 磁盘 I/O 危机已处置**：当日宿主机 sda 机械盘 I/O stall（其他项目重负载叠加），采取停让负载 + 宿主机直部署完成全部运行；zhixiu-ai-worker-temporal-dev 的重启死循环为持续 I/O 隐患，重拉栈后需重新 `docker update --restart=no`。

## 3. 已就绪的自动化（本目录）

- `run-evidence-pack.sh` — 一键流水线：preflight → 装 AgentTeams v1.2.2（钉死 commit+SHA256）→ DeepSeek LLM 链路预检 → 起 CyberGuard 双服务 → Higress 注册两个工具服务（凭据只进网关）→ 分发 10 个 Skill + 建 7-Worker Team → readiness 闸门 → **发 WebShell 任务到 Team 房间并全程抓取** → 终态导出 → 回滚演示 → 打包 tar.gz+SHA256SUMS。
- `capture_task.py` — Matrix 原生事件链采集器（复用 benchmark/matrix_runner.py 的客户端）：发任务、落盘全部房间事件、每 30s 快照 incident/审计状态、**识别待审批动作并提示人工审批命令**。

审批环节需要真人执行（这是设计要求的"人工在环"）：

```bash
bash scripts/approve-action.sh ACT-xxxxxxxxxxxx shuuyou   # 或 armaygooser
```

## 4. 复赛提交清单对照（手册 §6.2，9.3 截止）

| 材料 | 状态 | 还差什么 |
|------|------|----------|
| 更新版项目方案 PPT | 初赛 19 页已有 | 加「完整场景链路」一章（用本次证据包截图/Trace）；加 SOTA 对标（见 §5）；更新「运行验证与风险边界」为真实数据 |
| 可执行 AgentTeams 代码包 | v0.12.0 仓库已满足 | 把证据包流水线脚本（本目录两个文件）合入仓库；README 补「真实任务证据复现」一节；release v0.13.0 |
| 可运行 Demo / Demo 视频 | 未录 | 流水线跑通后录屏：发任务 → 7 Agent 协作 → L2 暂停 → 人工审批 → 执行 → 独立复测 → 报告 → 回滚演示，配审计台（`:18100/console`）画面，5-8 分钟 |

## 5. SOTA 对标论据（答辩/PPT 用，截至 2026-08 调研）

- **底座**：AgentTeams（原 Hiclaw）v1.2.3 已带 DAG 可视化与人工干预闭环，5.5k stars、吉利等企业案例——框架是"协作治理平面"，**不含审批哈希绑定/HMAC 防篡改链/回滚/复测**，这些恰是 CyberGuard 的领域创新层，答辩切口就是"我们不重复造底座，我们补的是底座没有的安全工程闭环"。
- **学术**：SOCpilot（200 起真实 SOC 事件）显示 LLM 响应方案违规率 36–87%，确定性校验器拦下 466 个违规审批动作 → "提示词写政策不可靠，执行边界才可靠"直接支撑审批哈希绑定设计；Cyber Defense Benchmark 显示最强模型开放式狩猎召回仅 3.8% → 论证工程化护栏必要性。
- **业界**：MS Copilot / Google SecOps / CrowdStrike Charlotte / Purple AI / 阿里 Agentic SOC 的 HITL 全部停留在"事后反馈"或"建议不执行"，**执行前强制审批+哈希绑定、动作级回滚、独立复测、HMAC 链式审计四件套在公开资料中未见覆盖**（措辞一律标注"截至 2026-08 公开资料未查到"）。
- **评测**：现有 agent 安全 benchmark（Cybench、NYU CTF 等）无一评测审批/回滚/审计维度 → 可主张"赛道首创评测维度"，配合仓库已有的 40 跑消融矩阵（4 变体×2 场景×5 次，matrix_runner 已就绪）。
- **完整调研纪要（含来源 URL）**：见会话记录或向 Kimi 索取。

## 6. 倒计时时间表（按 9.1 新规更新）

| 日期 | 动作 |
|------|------|
| 9.1 | 新规同步（Notion+仓库）；Demo 视频开剪：8 分钟完整版（提交用）+ 1 分钟精华版（答辩用） |
| 9.2 | 更新 PPT：**标红初赛反馈调整点**（真实 AgentTeams 任务证据包）+ 场景闭环图 + SOTA 对标页；v0.13.0 release（挂证据包 tar.gz 为 release asset） |
| 9.3 | **复赛作品提交截止**：PPT + 代码包 + 完整链路验证材料 + 8 分钟 Demo 视频 |
| 9.3 晚 | 全流程彩排（3 分钟陈述 + 1 分钟 Demo 掐表）+ 设备测试 |
| 9.4 | **答辩日：15:18 前候场，15:28—15:36 正式答辩**；会议昵称「23号+姓名+队名」 |

## 7. 答疑会已错过？

评委线上答疑会 8.27 19:00-21:00 已结束。未参会不影响评审；如有问题走钉钉群 186080014742。
