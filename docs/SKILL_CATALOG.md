# CyberGuard Skill Inventory

十个 Skill 均为版本化 `SKILL.md` + ZIP 包，带 SHA256 校验；共同输出结构化状态与可追溯证据，缺失真实工具回执时只能返回 `PARTIAL`、`BLOCKED` 或 `INCONCLUSIVE`。

| Skill | Applicable | Input | Tool/MCP | Output | Safety / Failure | Reuse |
|---|---|---|---|---|---|---|
| alert-triage | 多源告警初筛与归并 | incident_id、告警窗口 | alert.snapshot、asset.context | 告警簇、假设、Evidence ID | 不把相似性当因果；缺数据 PARTIAL | SIEM/告警平台 |
| threat-intel-enrichment | IOC/实体情报富化 | observable、incident_id | intel.lookup | 情报线索、置信度、Evidence ID | 情报不代替现场证据 | CTI/TIP |
| network-hunting | 流量与会话调查 | 时间窗、实体/IOC | network.search | 会话事实、时间线、Evidence ID | 不补写 IP/端口 | NDR/NetFlow/PCAP 索引 |
| boundary-defense | 边界策略核验 | 资产、路径、策略对象 | boundary.policy | 有效策略、暴露面、Evidence ID | 不声称未验证策略生效 | 防火墙/WAF/网关 |
| endpoint-forensics | 终端与运行时取证 | 资产、时间窗 | endpoint.timeline | 进程/文件/登录时间线、Evidence ID | 不以题面代替 EDR 回执 | EDR/HIDS/云运行时 |
| hypothesis-testing | 跨源假设验证 | 假设、支持/反驳证据 | 只读证据工具 | SUPPORTED/CONTRADICTED/PARTIAL | 至少满足质量门才升级结论 | 通用调查流程 |
| response-planning | 最小可逆处置规划 | 已验证证据、风险、资产上下文 | 响应提案接口 | 精确 action/target、回滚、审批级别 | L2 必须等待人工审批 | SOC/SOAR |
| controlled-response | 白名单受控执行 | 提案哈希、审批、幂等键 | 响应执行 MCP | Action ID、审计记录、状态 | 未批准/不匹配一律拒绝；支持回滚 | IAM/隔离/边界执行器 |
| recovery-verification | 独立恢复复测 | 完整 Action ID 集、恢复窗口 | recovery.metrics | VERIFIED/INCONCLUSIVE、Evidence ID | 缺少任一动作或证据不得成功 | 事件恢复/SRE |
| incident-reporting | 事件与审计汇总 | 状态机、证据、动作、验证 | 只读审计接口 | 结构化摘要、时间线、残余风险 | 不覆盖或美化失败状态 | SOC 报告/合规审计 |

精确输入输出、步骤、安全边界、失败状态和质量门以各目录中的 `skills/*/SKILL.md` 为准；Worker 与 Skill/MCP 权限的真实绑定由 `deploy/validate-agentteams-state.py` 从 Worker 资源快照校验。
