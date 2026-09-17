---
name: recovery-verification
description: 独立检验遏制效果，不依赖规划者叙述，不把零告警当作恢复证明。
version: 1.2.0
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

### 执行模式与实验室适配器

- 场景 fixture 的 `verification_scope=simulated_response_contract` 只证明模拟契约，不能作为真实环境恢复证据。
- 使用 `scenario_id=lab_identity` 时，必须向 `recovery.metrics` 传入本次 `run_id` 和 `action_id`。该适配器只验证隔离身份服务中的 `compromised-lab` 账号禁用。
- 检查返回的环境 ID、`checks[]` 内目标账号与对照账号的独立访问结果、随机 nonce 和观测时间。`verification_scope=point_in_time_lab_access` 仅表示观测时刻的访问状态，不代表持续恢复或生产业务 SLO。
- 执行回执为 `applied` 不能直接判定 `verified`；缺失探针/凭据错误/运行绑定不符应为 `inconclusive`，真实观测与目标相反应为 `failed`。通用 live connector 尚无专用核验契约时保持 `inconclusive`。
- 此 Skill 修改尚不代表已在运行中的 AgentTeams Worker 安装或执行；发布后须重新分发并保留加载与调用证据。

仅返回 `verified`、`failed` 或 `inconclusive` 之一，并包含 `matched_actions[]`、`security_checks[]`、`business_checks[]`、`telemetry_health`、`window`、`evidence_ids[]`、`rollback_recommendation`。

## 失败处理、复用与质量

指标接口失败或批准集合不完整时结果为 `inconclusive`，不使用旧结果替代。输出可进入事件报告和审计。质量门：独立回执、动作逐项匹配、双维结果、可解释的不确定性。
