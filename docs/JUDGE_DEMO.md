# 决赛演示与录制脚本

**主线：一次执行成功，为什么还需要再次调查和处置？**

[评委入口](FINALS_ENTRY.md) · [亮点证据表](PROVEN_CAPABILITIES.md) · [完整运行记录](FULL_CASE_VALIDATION.md)

新版主片展示同一现场案件：原生调查、具体提案、审批执行、失败观测、新一轮原生调查和再次验证。[观看演示](https://github.com/elsechord/CyberGuard/releases/download/v0.15.0/cyberguard-finals-20260920.mp4)。录屏为已完成运行回看，实际案件耗时 11 分 18 秒，批准由测试框架调用真实审批 API。

## 先准备这几个窗口

- Console `/connect`，展示可供已有 Agent 复制的 Skill 连接指令。
- 第一次原生调查 `INV-5a259d4dbdb9410f87ea4b1511a7cd8f`：打开任务分工、报告与原文引用。
- [同案现场证据阅读器](validation/live-response/LIVE-HOST-a3f9b38ac1a349b9ab1b7617b1a1d959/review.html)：原始提案、批准绑定、执行回执与复核结果。
- 第二次原生调查 `INV-183181f645814f4db17eb6e24128ac7f`：由第一次失败后的实时证据触发，随后进入第二次提案与验证。
- [交互运行说明](LIVE_RESPONSE_DEMO.md)：需要现场真人审批时，以 `--interactive` 运行并逐份输入批准。

## 主片顺序（约 80 秒）

| 镜头 | 实际画面 | 讲解重点 |
| --- | --- | --- |
| 连接 | `/connect` 的 Skill 连接指令 | “继续使用已有 Agent，把调查交给后台。” |
| 第一次调查 | 本案第一轮 Console 任务与报告 | “AgentTeams 原生分工，调查与复核分由不同 Worker 完成。” |
| 第一次处置 | 本案提案和批准摘要、failed 观测 | “首次按操作员范围只停止进程。操作成功，但进程重新出现。” |
| 再次调查 | 本案第二轮 Console 任务与报告 | “失败不是终点，新的实时证据进入下一轮调查。” |
| 再次处置 | 新提案与 verified 结果 | “重新批准具体方案后，处理持久化，再检查实际效果。” |
| 交付 | 同案记录与仓库入口 | “每一步都能回到证据。” |

片中提案由受约束转换器将原生调查报告映射为允许动作。原生任务、转换器、审批和执行器各自承担明确职责。环境是隔离的无害进程实验；自动验收批准与现场真人批准分别标注。013 / 014 合成历史材料调查回放作为独立重复性证据保留在[完整案件验证](FULL_CASE_VALIDATION.md)。

## 四分钟答辩

- **0:00–0:55，场景：** 杀掉进程后它重新出现。现有工作流需要知道：依据是什么、批准了什么、结果是否真正达标。
- **0:55–1:20，架构：** 材料与 Skill → Console → AgentTeams 原生 Task → 调查与复核；处置路径由具体提案、审批、执行器和效果探针组成。
- **1:20–2:55，亮点与演示：** 重点停在“执行成功但复核失败”，展开一条原文引用、一张审批对象和一项独立观测。
- **2:55–3:30，接入价值：** 保留已有 Agent 入口与 SOAR 执行接口，先做只读调查，逐步进入受控处置。
- **3:30–4:00，开源：** 展示评委入口、可复现运行和 Skill 安装方式。把完整哈希、日志和调用量留作追问入口。

## 现场检查

确认登录、材料、任务和报告都已打开；关闭系统通知；隐藏密钥与私人路径。模型现场实跑会受网关延迟影响，同案原始记录与录像作为离线展示备份。讲实跑耗时，不承诺每次固定在同一时间完成。

问到稳定性与成本时，区分两个证据集：013 / 014 相同配置两次调查回放通过关键验收，231.9 / 307.2 秒；新的同案现场闭环 677.60 秒、20 项检查通过。调用量和失败尝试见[完整记录](FULL_CASE_VALIDATION.md)，下一步优化重点是重复上下文和调度开销。

## 旧服务验收入口

以下保留用于检查审批、审计与回滚接口。它与最新原生调查记录各有用途，旧 82 秒视频对应此类服务流程。

## Prepared deterministic service check

Prerequisite: a Linux/Bash host with Python 3, curl and GNU coreutils, a generated `.env`, and the baseline `compose.yaml` services already healthy. Follow [QUICKSTART.md](QUICKSTART.md) first, including creation of the external `agentteams-net` network. No model key or running AgentTeams/Matrix deployment is needed for this script.

1. Open the read-only audit view at `http://127.0.0.1:18100/console` (SSH-forward this loopback port when using a server).
2. Run `bash deploy/judge-demo.sh` as a user able to read the local `.env`. It does not rebuild or alter configuration, but creates test incidents and response records.
3. Select the newly generated `E2E-*` incidents in the audit view and inspect evidence, approval records, recovery results and rollback.
4. Open `artifacts/demo/<timestamp>/demo-summary.json` and `SHA256SUMS` as the machine-readable result. Check with `(cd artifacts/demo/<timestamp> && sha256sum -c SHA256SUMS)`.

The script runs both fixed scenarios with **simulation execution** in the baseline Compose deployment. Each collects fixture evidence and executes the three exact actions declared by that scenario's recovery contract. It checks recovery before the response set, rejects unapproved execution, verifies the complete approved set, validates the audit chain, and checks that rollback invalidates recovery. The harness supplies the approval credential itself (`server-e2e-test`); this is not actual human review or an Agent/LLM investigation.

The current script does **not** check recovery between the first and third actions and does **not** demonstrate a failed post-execution verification followed by a revised proposal. Do not present it as that full exception-handling storyline. The separately retained [live AgentTeams task evidence](LIVE_TASK_EVIDENCE.md) records a wrong-target proposal and subsequent correction; its recovery contract is deterministic too. The [host laboratory](HOST_LAB.md) independently observes harmless real processes restarting after termination and is the separate entry point for an actual-state failure demonstration. Neither is a production intrusion remediation claim.

The multi-user operations console is a separate surface on port **18120**, with first-admin setup and session requirements described in [OPERATIONS_DEPLOY.md](OPERATIONS_DEPLOY.md). Matrix role lanes belong to a separately running AgentTeams task; the deterministic script does not generate them.

## Run correlation one-pager

`scripts/export-run-correlation.py` renders an offline Markdown + JSON one-pager per incident (optionally per `--run-id`) from a gateway data directory's `evidence.jsonl` / `workflow.jsonl`: one merged timeline of workflow transitions (including human approval waits) and evidence collection, plus quality metrics, envelope-integrity checks and pointers to the authenticated run export and audit chain. No service needs to be running. See `docs/examples/run-correlation-CG-2026-0002.md` for the console-demo incident.

```bash
python scripts/export-run-correlation.py CG-2026-0002 --data-dir <gateway-data-dir> \
  --output run-correlation-CG-2026-0002.md --json-output run-correlation-CG-2026-0002.json
```

The view correlates gateway-side evidence and workflow only. Native Matrix/AgentTeams task events (Task, Worker, Skill versions, model usage) are referenced as a pointer to [LIVE_TASK_EVIDENCE.md](LIVE_TASK_EVIDENCE.md), not covered by this view.
