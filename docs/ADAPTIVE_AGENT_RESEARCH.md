# 自适应 Agent 协作：研究依据与 CyberGuard 实施取舍

调研截止：2026-09-20。本文核验原始论文、会议论文或官方项目资料；论文中的数字是作者报告的结果，**没有在 CyberGuard 上复现**。不同数据集、模型和预算下的结果不能直接横向排名，因此本文不宣称存在通用最优架构。

## 本轮决定

优先使用 **AgentTeams 原生 Task 与 WorkerFlow 临时子 Agent**：Leader 根据任务依赖安排调查和独立复核，Worker 在存在可独立完成的问题时展开局部并行，结果回到所属 Worker，再进入原生 Task 验收。

本轮不实现 Docker Worker 弹性集群。团队成员、Worker 内临时子 Agent、原生 Task 是三个不同概念，界面和文档应分别记录，不能把临时子 Agent 数量称为容器扩容。人数上限和启用规则是可调整的工程选择，不能称为已经验证的 SOTA 策略。

## 最值得采用的研究结论

| 来源与版本 | 作者报告的结果 | 对 CyberGuard 的启示与边界 |
| --- | --- | --- |
| [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296v3)，v3，2026-04-08 | 在 260 种配置、6 个基准上比较单 Agent 与四类多 Agent 架构。相对表现从可拆分金融任务的 +80.8% 到串行规划任务的 -70.0%；预测模型在留出配置上选中最佳架构的比例为 87%。 | 是否可分解比人数重要。独立证据分支适合并行；严格串行、工具密集任务可能被协调开销拖累。不是 SOC 专用结论，也不是所有任务都可获得这些收益。官方早期博客使用 180 配置数据，不能与此版本混写。 |
| [Learning How Much to Collaborate / DATS](https://arxiv.org/abs/2609.13890v1)，v1，2026-09-12 | 在 614 道代码任务上按预测成功率与成本选择拓扑；作者报告使用固定层级方案 40% 的成本时，pass@1 达到 77.7%，固定层级方案为 73.6%。 | 借鉴“最少足够协作”和同预算评测。属于新近论文，本轮未核实正式录用或复现；不能把代码题路由器的准确率转移到安全调查。 |
| [AgentDropout](https://aclanthology.org/2025.acl-long.1170.pdf)，ACL 2025；初稿 2025-03-24 | 按轮次移除冗余 Agent 和通信边；作者报告提示与输出 token 平均分别下降 21.6% 和 18.4%。 | 已完成局部工作即可停止参与，不必让所有成员读所有消息。本轮不引入其可训练邻接矩阵；只借鉴减少冗余参与的原则。 |
| [SupervisorAgent](https://arxiv.org/abs/2510.26585v2)，ICLR 2026；v2，2026-03-02 | 由不调用 LLM 的过滤器触发必要干预；在 GAIA/Smolagent 上，作者报告 token 减少 29.68%，成功率不降。 | 在阻塞、错误或信息缺口出现时重规划，避免每一步都新增监督模型调用。论文节省比例不是 CyberGuard 的承诺。 |
| [DynaDebate](https://arxiv.org/abs/2601.05746v2)，v2，2026-06-15 | 提出不同推理路径、过程层面的争议检查，以及在分歧出现时使用外部工具的验证者。 | 围绕具体事实和原始证据求证；不要以多数 Agent 同意代替事件事实或执行效果。论文实验不能证明安全调查归因可靠。 |
| [AgentDropoutV2](https://arxiv.org/abs/2602.23258v2)，v2，2026-05-28 | 利用历史失败模式辅助纠错，对无法修复的信息停止传播；数学与代码基准的平均准确率分别提高 6.39 与 2.28 个百分点。 | 不把未经验证的上游推断升级成事实。暂不照搬额外内容审查层：该方法需要历史失败轨迹，也会引入新的计算成本。 |
| [Multi-Agent Collaboration via Evolving Orchestration](https://proceedings.neurips.cc/paper_files/paper/2025/file/f1320d2e2842169c6fc89dcbd80e94d0-Paper-Conference.pdf)，NeurIPS 2025 | 用强化学习训练中央编排器按状态选择 Agent；作者观察到紧凑、有回路的协作结构。 | 允许“调查—复核—补证”的必要回路。当前缺少足够任务与可靠奖励信号，不训练新的 RL 编排器。 |

较新的 [AGAO](https://arxiv.org/abs/2607.23678v1)（2026-07-26）提出按目标相关性、依赖和计算资源分配执行优先级。本轮仅核验摘要与版本日期，未独立核查完整实验，保留为后续研究线索，不作为当前性能结论依据。

## 映射到现有架构

### 任务与临时子 Agent

Leader 先识别需要回答的问题，而不是先指定人数。例如登录来源、进程行为、网络连接可以形成不同证据分支；仅仅日志变长，不自动意味着需要更多 Agent。

原生 Task 负责可追踪的委派、提交、返工和验收。WorkerFlow 临时子 Agent 用于其中的局部工作，每次创建应明确问题、所需输入和返回产物。所属 Worker 汇总结果并承担 Task 提交责任，临时子 Agent 的结束不能等同于原生 Task 已验收。

不要并行复制多个相同角色后以投票收尾。同一原始材料衍生的多份回答仍共享证据来源，不能被计为多条独立证据。

### 通信与上下文

采用 Leader 统筹、成员定向求证的协作方式。Worker 可以反馈缺口、冲突和补充材料请求，也可以向掌握相关证据的成员提问。消息应包含明确问题、证据 ID 或产物路径以及必要片段，减少重复传播整段历史。

需按实际接口区分 Worker 间 Matrix 通信与 WorkerFlow 内部父子通信。只有完成运行验证后，才能宣称对应路径支持双向交互；具备工具配置不等于链路已验证。

### 复核与停止

独立复核者依据原始材料和验收条件检查结果，不仅润色调查员的输出。存在争议时检查相关事实、补取证据；不能用群体共识替代核验。对执行效果的检查应与执行器的成功回执分开。

满足问题覆盖和验收条件时收尾；缺少外部材料时明确未解项；持续没有新证据时请求补充材料，而不是持续创建 Agent。保留并发、预算和嵌套深度等少数运行边界，不另设每步审批或重复工具白名单。这些是本项目的工程建议，不是论文证明的最优停止规则。

## CyberGuard 应形成的特色

动态创建 Agent 本身已经不是稀缺能力。可形成差异的是把协作决定连接到调查证据：为什么新增一项调查、它补哪个缺口、用了什么原始材料、谁检查了结果、为什么停止或交给人。

现有证据引用、原生 Task、方案审批与独立复核可以共同呈现这个过程。对用户展示任务与产物的关系，比展示大量 Agent 头像更有意义。评审时应区分“调用成功”“调查有依据”“处置效果通过复核”三个状态。

## 验证计划与尚未验证部分

研究结论不替代产品验证。当前实现和运行状态以任务服务文档及实际验收记录为准；本文不证明下面场景已经通过。

| 场景 | 需要观察的实际行为 |
| --- | --- |
| 简单单源问题 | 不发生无意义的临时 Agent 扩张，仍产生可引用结果。 |
| 多源可独立问题 | 实际发生 WorkerFlow 子任务并行，父 Worker 能收回产物，原生 Task 正常提交和验收。 |
| 证据冲突 | 定向求证与向 Leader 反馈能够完成；证据不足时保留未解结论。 |
| 执行器报告成功但效果不达标 | 独立复核指出具体未满足条件，触发补证或重新提案。 |

与固定团队方案比较时，使用相同模型、材料和相近预算，记录任务成功率、引用正确性、复核漏检、总 token、耗时、活跃子 Agent 数量及人工恢复次数。只有运行证据支持后，才报告成本或质量改善。

Docker Worker 自动扩缩容、学习式拓扑路由、跨模型复核增益以及长周期无人值守稳定性均不包含在本轮已验证能力之内。


## 业界官方实践

| 来源（截至 2026-09-20 核对） | 可借鉴内容 | 本轮取舍 |
| --- | --- | --- |
| [Anthropic 多 Agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)，2025-06-13 | 对可并行研究明确问题、产物和边界；限制重复探索 | 每个临时专家都有 question、material_ids 和分工理由；不复制全部聊天历史 |
| [Anthropic emerging multiagent systems](https://www.anthropic.com/research/multiagent-systems)，2026-08-13 | 安全研究中采用协作交流、peer review 与独立裁决 | 专家可以求证，独立 verifier 保留。其 266 vs 21 漏洞结果不是等范围、等 token 比较，不能直接作为收益证明 |
| [Claude Agent SDK subagents](https://code.claude.com/docs/en/agent-sdk/subagents) | 动态角色、上下文隔离、定向消息及资源边界 | 原生临时角色、父子标识、按需通信；不额外移植另一套调度器 |
| [LangChain subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents) | 区分同步与后台任务，返回摘要，需要时读原始材料 | 专家短回复与原始引用并存；运行状态以原生任务数据为准 |
| [Microsoft group chat orchestration](https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/group-chat) | 并行独立任务与交互式群聊是不同模式 | 只在具体问题或冲突出现时定向问答，不默认全连接群聊 |

上述产品能力是调研时的官方文档描述；CyberGuard 的部署只使用实际核对过的 AgentTeams v1.2.3 原生能力。临时 Agent 共享父 Worker 的模型通道，不能宣称已有子 Agent 独立计费。

## 已落地的实现位置

- `deploy/investigation-service/collaboration/`：原生 WorkerFlow 薄封装、协作 Skill 和三种角色模板。模型选择由父 Worker 显式传入，生命周期通过原生 API 完成。
- `deploy/investigation-service/install-collaboration.py`：安装模板/Skill/helper，并回读原有模型、工具与通信配置。
- `services/operations-console/app/agentteams_native.py`：向 Leader 传达按需协作要求，从原生 Task artifact API 读取可选 collaboration.json。观测缺失不阻断调查。
- `services/operations-console/app/collaboration_view.py`：区分团队 Worker、临时 Agent 和任务，展示分工、状态和定向问题记录。

默认 0–3 个临时专家是每次内部协作的工程配置，零表示直接调查、不启动 WorkerFlow。helper 限制单次创建数量和父层级，但不是全平台并发配额。节点状态来自原生 workflow.json；消息日志是 Agent 记录的交互摘要，单独的 event_id 不能冒充已验证传输凭证。
