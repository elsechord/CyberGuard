# CyberGuard：亮点与证据

> 调查需要证据，授权需要对象，执行需要复核。

CyberGuard 将这些要求做成 Agent 可调用、团队可部署的基础设施。以下每项都提供代码或运行记录入口，评委可以从产品价值直接追到实现。

| 亮点 | 带来的价值 | 已有证据 |
| --- | --- | --- |
| **已有 Agent，一条 Skill 接入** | 保留用户熟悉的交互入口，后台接手持续调查，调用方可稍后取回结果 | [Skill 与连接流程](EXTERNAL_AGENT_SKILL.md)；[014 原始请求](validation/full-case/014/request.json) → [返回报告](validation/full-case/014/skill-report.json) |
| **AgentTeams 原生任务协作** | Leader 规划、委派和验收；调查与复核分由不同 Worker 承担，过程可追踪 | [014 原生工作流](validation/full-case/014/workflow.json)；[后端实现](../services/operations-console/app/agentteams_native.py) |
| **按需专家与双向沟通** | 专家可以向同伴与父 Worker 提问，保留问答与回收记录 | [1 / 2 名专家生命周期检查](validation/adaptive-collaboration/native-lifecycle.json)；[真实模型的子 Agent ↔ 同伴 / 父 Worker 往返](validation/adaptive-collaboration/native-communication-summary.json)。这是独立协作探针，013 / 014 无临时专家 |
| **从材料到结论保留依据** | 用户可以回到原文核对判断，而不是只收到一段模型总结 | [四份原始材料](validation/full-case/014/materials.json)；[8 条结论、16 条逐字引用](validation/full-case/014/skill-report.json)；[校验与语义审阅](validation/full-case/014/semantic-review.json) |
| **执行成功之后，仍要检查效果** | 避免将“停止了旧进程”误判为“威胁已经清除” | [014 报告](validation/full-case/014/skill-report.json)识别第一次处置未达标；[真实进程实验](HOST_LAB.md)展示无害进程被持久化机制重新拉起 |
| **同案调查、处置、失败后再调查** | 新效果观测真正进入下一轮调查和决策，案件不因命令成功而提前结束 | [同案原生完整链路](LIVE_RESPONSE_DEMO.md)：677.60 秒、20 项检查；[原始产物](validation/live-response/LIVE-HOST-a3f9b38ac1a349b9ab1b7617b1a1d959/)包含两轮原生任务、提案、批准与 failed → verified |
| **审批绑定具体方案** | 换对象、改参数就需要重新确认；授权可以追溯到具体动作 | [响应执行器](../services/response-executor/)；[隔离实验的审批与执行](HOST_LAB.md) |
| **同一案件可以重复运行** | 提交、任务、报告、耗时与调用量都有记录，可复算而非只看剪辑 | [013 / 014 汇总](validation/full-case/summary.json)：相同配置连续完成，提交后零人工补发指令 |

**实跑数据。** 013：307.2 秒、50 次模型请求、7 条结论 / 22 条引用；014：231.9 秒、35 次请求、8 条结论 / 16 条引用。输入分别为 1,854,537 / 1,127,317 token，输出为 38,505 / 30,109 token。费用以所用模型网关实际计价为准。

**如何读这些证据。** 013 / 014 是合成挖矿事件的真实模型调查回放，R1 / R2 是输入材料中的历史处置记录。真实进程实验则在隔离容器中操作无害进程与文件，支持交互审批，自动化验收使用测试审批。新增[同案现场运行](LIVE_RESPONSE_DEMO.md)将每轮实时证据提交 AgentTeams 原生调查，再将本轮报告交给受约束提案转换器，经过审批、实际执行和独立效果探针完成 failed → 新调查 → 再提案 → verified。该运行使用自动测试审批，现场交互模式逐份输入批准。关键案件结论由 Codex 在运行后语义审阅，原报告保留原样；具体运行条件、失败尝试和措辞注记见[完整验证记录](FULL_CASE_VALIDATION.md)。

**产品切入。** 先为安全团队提供只读调查与复核，通过现有 SOAR 或厂商接口接入处置；用一个明确场景验证分析师时间、审阅负担和复用成本。开源核心覆盖材料接入、原生任务适配、审批约束、效果检查与复现工具，企业交付围绕组织接入、部署维护和专用连接器展开。
