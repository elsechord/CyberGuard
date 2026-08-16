---
name: controlled-response
description: 仅在审批、范围和回滚均已验证后执行白名单安全动作。
version: 1.1.0
---

# 受控响应（Controlled Response）

## 适用条件与依赖

仅由受控响应角色使用，依赖响应 MCP 的提议、审批状态、执行、审计查询接口。允许动作仅为 `block_ioc`、`disable_account`、`isolate_endpoint`、`quarantine_workload`。

## 输入

已批准的 `incident_id`、`proposal_id`、精确 `action/target`、`idempotency_key`、审批记录、回滚方案和验证计划。任何字段缺失均不可执行。

## 执行与安全边界

1. 严格执行“提议 → 人工审批 → 执行”三阶段；禁止伪造、猜测或复用过期审批。
2. 执行前比对事件、目标、动作、幂等键、审批新鲜度、授权范围和回滚可用性；与已批准提议不完全一致即停止。
3. 多动作必须逐项提议、逐项审批、逐项保留 Action ID；不得以相近目标替换批准目标。
4. L0 只读自动；L1 仅在项目策略明确允许时自动；L2（禁用账号、隔离端点）必须人工审批；L3 只产出计划。
5. 部分失败立即停止后续动作，保留审计记录，转恢复核验或回滚；禁止宣称恢复成功。

## 输出契约

输出 `proposal_id`、`approval_reference`、`executed_actions[]`（含 Action ID、审计哈希、状态）、`skipped_actions[]`、`rollback_handles[]`、`verification_required`、`status`。

## 失败处理、复用与质量

审批失效、目标漂移、回滚不可用或工具异常均为 `BLOCKED`，并输出阻断原因。Action ID 交给 recovery-verification 独立核验。质量门：执行动作与审批逐项一致、审计哈希存在、无越权动作、所有高风险动作可回滚。
