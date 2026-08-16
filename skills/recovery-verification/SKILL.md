---
name: recovery-verification
description: 独立检验遏制效果，不依赖规划者叙述，不把零告警当作恢复证明。
version: 1.1.0
---

# 恢复核验（Recovery Verification）

## 适用条件与依赖

在响应执行后由独立核验角色使用。依赖只读 MCP `recovery.metrics`、已批准动作集合和实际 Action ID；不得由同一执行 Agent 自证成功。

## 输入

`incident_id`、`scenario_id`、完整批准动作集合（action/target/Action ID）、核验时间窗、业务容忍度和回滚句柄。

## 执行与安全边界

1. 独立调用 `recovery.metrics`，将 `verified_actions` 与完整批准集合逐项比对。
2. 部分集合、错误目标、无关动作、必要动作已回滚、遥测不健康均为 `inconclusive`，不得标记 `verified`。
3. 同时验证安全结果（攻击者访问/可疑流量消失）与业务结果（合法服务持续）；尝试证伪恢复主张。
4. 零告警本身不足以证明恢复；明确观测窗口、遥测健康度和残余风险。
5. 业务伤害超过审批容忍度时建议回滚，但不得自行执行回滚。

## 输出契约

仅返回 `verified`、`failed` 或 `inconclusive` 之一，并包含 `matched_actions[]`、`security_checks[]`、`business_checks[]`、`telemetry_health`、`window`、`evidence_ids[]`、`rollback_recommendation`。

## 失败处理、复用与质量

指标接口失败或批准集合不完整时结果为 `inconclusive`，不使用旧结果替代。输出可进入事件报告和审计。质量门：独立回执、动作逐项匹配、双维结果、可解释的不确定性。
