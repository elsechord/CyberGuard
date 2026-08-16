---
name: boundary-defense
description: 评估边界策略与网络证据，提出最小、可逆的边界遏制建议，不直接改策略。
version: 1.1.0
---

# 边界防御（Boundary Defense）

## 适用条件与依赖

适用于疑似跨互联网、云、Kubernetes 或信任区的事件。依赖只读 MCP `boundary.policy`、`network.search`；本 Skill 是调查和规划能力，不得调用响应执行器。

## 输入

`incident_id`（必填）、`scenario_id`（演练必填）、实体/IOC、受限时间窗、业务例外（可选）。

## 执行与安全边界

1. 用 `boundary.policy` 查询有效规则、执行点、源/目的区和动作，再以 `network.search` 验证实际流量。
2. 明确区分“策略可达”与“流量已发生”；记录两个来源的 MCP 回执、Evidence ID、质量和缺口。
3. 仅当证据支撑时判断路径为显式允许、隐式允许、拒绝或未知；为每个结论列出支持和反驳证据。
4. 如需遏制，只提出精确 `block_ioc` 建议：目标、执行点、影响区、到期/回滚、业务冲突和验证方法。通配符、共享 CDN、生产入口、控制面或 CIDR 扩张必须人工审查。
5. 禁止从域名推导“所有解析 IP”、从信誉推导授权、从无流量推导策略已生效；禁止虚构规则名、网段或 Evidence ID。

## 输出契约

输出 `effective_policy`、`path_evidence[]`、`classification`、`risk`、`proposal|none`、`rollback`、`verification`、`evidence_gaps[]`、`status`。每个事实均须含可解析 Evidence ID。

## 失败处理、复用与质量

任一工具不可用时为 `PARTIAL/BLOCKED`，并给出所需日志、时间窗和责任系统。结果可供响应规划与恢复核验复用，但不是执行授权。质量门：策略与流量均被独立核验、建议具备回滚、无宽泛目标、无未解析 Evidence ID。
