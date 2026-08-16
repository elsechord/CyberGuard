---
name: incident-reporting
description: 输出区分事实、假设、动作与剩余风险的可审计事件报告。
version: 1.1.0
---

# 事件报告（Incident Reporting）

## 适用条件与依赖

用于阶段性汇报、审批请求和演练结案。依赖共享状态、已验证 Evidence ID、Action ID 和恢复核验结果；不能替代调查或执行。

## 输入

`incident_id`、时间线、已确认事实、假设结论、Evidence Index、行动/审批/Action ID、核验状态、受众与信息分级。

## 执行与安全边界

1. 报告必须包含：执行摘要、时间线、受影响资产、确认事实、接受/拒绝假设、Evidence Index、ATT&CK 映射、行动与审批、核验、剩余风险和后续事项。
2. 所有重要结论必须引用可解析 Evidence ID 或 Action ID；事实、推断、建议和未知项分栏。
3. 未经独立恢复验证不得声称“已恢复/已清除”；未经审批不得声称“已执行”。
4. 按 handling 标记脱敏，不复制受限原始证据、密钥、个人数据或内部命令细节。
5. 禁止汇总时补写不存在的时间、资产、执行结果或证据。

## 输出契约

输出 `report_version`、`incident_id`、各必需章节、`evidence_index[]`、`action_index[]`、`disclosure_level`、`status`。`status` 与当前核验状态一致。

## 失败处理、复用与质量

引用不可解析或关键章节缺失时退回上游并输出 `PARTIAL`，不发布“最终报告”。报告可作为审计和经验沉淀输入。质量门：主张覆盖率 100%、证据索引可解析、信息分级正确、未知项显式呈现。
