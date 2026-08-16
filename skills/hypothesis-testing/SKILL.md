---
name: hypothesis-testing
description: 以支持、反驳与待验证证据比较竞争性事件假设。
version: 1.1.0
---

# 假设检验（Hypothesis Testing）

## 适用条件与依赖

适用于证据融合、根因判断和响应前决策。依赖共享事件状态及上游 MCP 回执；本 Skill 不直接产生安全事实或执行动作。

## 输入

`incident_id`、候选假设至少两项、每项预测观察、Evidence ID 清单、时间关系和数据缺口。

## 执行与安全边界

1. 为每个假设列出可证伪预测、支持证据、反驳证据、独立性、时间一致性和下一步测试。
2. 先解析 Evidence ID 的来源与质量，再评估相关性；来自同一原始日志的重复派生信息不得视作独立佐证。
3. 以校准后的定性等级与 0–1 置信度说明理由；禁止随意平均数字或用单一信誉命中断言根因。
4. 证据不能区分假设时明确输出“不可判定”，不得为了完成任务选择一个根因。
5. 禁止新增 Evidence ID、修改上游事实或把假设写成确认结论。

## 输出契约

输出 `hypotheses[]`（statement、predictions、supports、contradicts、remaining_tests、confidence、decision）、`unresolved_gaps[]`、`recommended_collection[]`、`status`。

## 失败处理、复用与质量

证据 ID 无法解析、来源不可信或时间窗冲突时标记对应假设不可用，并返回 `PARTIAL`。结果可供 Leader 与 response-planning 复用。质量门：至少两个假设、每项含反驳/缺口、无孤立证据被夸大、所有引用可追溯。
