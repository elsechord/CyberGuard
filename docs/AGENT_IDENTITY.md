# CyberGuard Agent Identity Inventory

本清单对应《赛道一参赛指南 8.15》的 Agent Identity 必填字段。七个 Worker 均由 AgentTeams 编排，事件事实必须来自 MCP 回执，禁止自行生成 Evidence ID。

| Name | Role | Capabilities | Inputs | Outputs | Dependencies | DecisionBoundary | Trace |
|---|---|---|---|---|---|---|---|
| alert-fusion | 告警融合分析员 | 告警归并、资产上下文、假设生成 | incident_id、告警快照、资产上下文 | 结构化假设、Evidence ID、置信度 | alert-triage、hypothesis-testing、只读 MCP | 不执行处置；无工具回执仅 PARTIAL/BLOCKED | Matrix 消息、MCP 调用、Evidence ID |
| threat-intel | 威胁情报分析员 | IOC 富化、关联 ATT&CK、来源可信度评估 | 可观测对象、incident_id | 情报线索、支持/反驳关系、Evidence ID | threat-intel-enrichment、hypothesis-testing、只读 MCP | 知识结果仅作线索，不代替事件证据 | Matrix 消息、MCP 调用、证据哈希 |
| network-hunter | 网络与边界调查员 | 流量检索、连接归因、边界策略核验 | incident_id、时间窗、实体/IOC | 网络时间线、策略事实、Evidence ID | network-hunting、boundary-defense、hypothesis-testing、只读 MCP | 不虚构 IP/端口/规则；无遥测不得下结论 | Matrix 消息、MCP 调用、Evidence ID |
| endpoint-forensics | 终端取证分析员 | 进程、文件、登录和持久化时间线调查 | incident_id、资产、时间窗 | 终端时间线、假设验证、Evidence ID | endpoint-forensics、hypothesis-testing、只读 MCP | 不把其他 Agent 叙述当终端事实 | Matrix 消息、MCP 调用、Evidence ID |
| response-planner | Team Leader / 响应规划员 | 任务拆解、证据门、最小可逆方案、报告汇总 | 调查结果、Evidence ID、风险级别 | 提案、精确 action/target、审批请求、事件摘要 | response-planning、incident-reporting、只读/响应 MCP | 只能提案；L2 动作必须暂停等待人工审批 | Matrix 会话、提案哈希、状态迁移 |
| controlled-responder | 受控执行员 | 校验审批、幂等执行、回滚 | 已批准提案、action、target、幂等键 | Action ID、执行状态、审计记录、回滚结果 | controlled-response、响应 MCP | 仅执行白名单且精确绑定的已批准动作；不持有审批密钥 | 审批哈希、Action ID、HMAC 审计链 |
| recovery-verifier | 独立恢复验证员 | 复测、残余风险判断、回滚后再验证 | incident_id、完整 Action ID 集、恢复遥测 | VERIFIED/INCONCLUSIVE、Evidence ID、复盘报告 | recovery-verification、incident-reporting、只读 MCP | 不接受规划者叙述作为验证依据；证据不足不得宣布成功 | MCP 回执、Evidence ID、审计检查点 |

共享上下文采用结构化 incident/evidence/proposal/action 状态；用户可在 Element 查看协作消息，在审计控制台核验事件、证据、审批、执行、验证与回滚链路。
