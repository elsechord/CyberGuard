---
name: response-planning
description: 设计最小、可逆、可审批且可验证的安全响应计划。
version: 1.2.0
---

# 响应规划（Response Planning）

## 适用条件与依赖

在告警、网络、端点及情报调查至少形成可解析证据后使用。依赖共享状态、Evidence ID 和响应 MCP 的只读提议能力；本 Skill 只生成计划，不执行动作。

## 输入

`incident_id`、已验证 Evidence ID、资产/业务关键性、候选目标、处置约束、批准策略和已知残余风险。

## 执行与安全边界

1. 对每项建议给出目标、理由、风险级别、爆炸半径、依赖、幂等键、预期结果、回滚和验证指标。
2. L0 只读自动；L1 低风险可逆动作仅按明确策略自动；L2（禁用账号、隔离端点）必须人工审批；L3 只输出计划。
3. 仅使用白名单 `block_ioc`、`disable_account`、`isolate_endpoint`、`quarantine_workload`；不得扩大为 CIDR、批量账号或非批准平台操作。
4. 多面暴露应定义完整最小动作集合，不能用一个方便动作假装彻底恢复；每项都绑定独立审批、Action ID 和核验条件。
5. 证据不足、目标不精确或回滚不可行时只提出补充采集，不提执行建议。

## 输出契约

输出 `plan_id`、`actions[]`（含 level、target、justification、evidence_ids、risk、rollback、verification、approval_required）、`preconditions[]`、`residual_risk`、`status`。

引用与状态一致性（网关强校验，违反将 422 拒绝整份报告）：finding 的状态决定证据引用字段——`confirmed` 的引用写入 `supporting_evidence_ids`；**`refuted` 的引用必须写入 `contradicting_evidence_ids`，不得放入 `supporting_evidence_ids`**；`inconclusive` 引用可留空并用 prose 说明缺口。

示例（正确）：

```json
{
  "finding_id": "F-3",
  "claim": "离岸登录来自合法管理员出差",
  "status": "refuted",
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": ["EV-0091", "EV-0104"]
}
```

错误写法：把 EV-0091/EV-0104 放入 `supporting_evidence_ids`（refuted 却声称"支持"）——网关以 "invalid investigation report: refuted claim requires collected evidence" 拒绝。

## 失败处理、复用与质量

Evidence ID 无法解析、审批策略未知或依赖未满足时标记 `PARTIAL/BLOCKED`。计划交给 controlled-response 与 recovery-verification 复用。质量门：一项一证据、一项一回滚、一项一核验；高风险动作未审批不可执行。
