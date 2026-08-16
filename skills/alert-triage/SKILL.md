---
name: alert-triage
description: 归一化、关联并分级安全告警；在证据不足时输出缺口，不提前认定根因。
version: 1.1.0
---

# 告警研判（Alert Triage）

## 适用条件与依赖

当收到新的 `incident_id`、告警包或多个可关联告警时使用。本 Skill 依赖只读 MCP 工具 `alert.snapshot` 与 `asset.context`；未取得工具回执时不得输出“已确认”事实。

## 输入

`incident_id`（必填）、`scenario_id`（演练必填）、已知实体/时间窗（可选）、业务影响约束（可选）。保留原始 `incident_id`，不得改写或另造编号。

## 执行与安全边界

1. 调用 `alert.snapshot`，再按受影响实体调用 `asset.context`；记录每次调用的回执、Evidence ID、时间与质量门。
2. 归一化账号、主机、IP、域名、哈希、告警类型和时间范围；只有共享实体且存在可解释的时间/因果关系时才可合并。
3. 至少保留两个竞争性假设，按业务影响、资产关键性、权限及已观测活动给出 P0–P4。
4. 输出事实、假设、缺口严格分栏。Evidence ID 必须来自 MCP 回执；禁止自行生成、转述未经核验的 ID，禁止把题面描述扩写为日志事实。
5. 不执行任何变更，不在 Matrix 房间粘贴受限原始证据；仅引用 Evidence ID。

## 输出契约

返回结构化结果：`incident_id`、`severity`、`normalized_entities`、`time_window`、`confirmed_facts[]`、`hypotheses[]`、`evidence_ids[]`、`evidence_gaps[]`、`assigned_investigations[]`、`status`。

`status` 只能为 `SUCCESS`、`PARTIAL`、`BLOCKED`；没有有效 MCP 回执时为 `BLOCKED`，数据不足时为 `PARTIAL`。

## 失败处理、复用与质量

工具超时/拒绝时保留错误码和请求范围，报告采集建议，不猜测数据。结果可作为威胁情报、网络和终端调查的共享状态输入。质量门：所有事实可追溯、实体去重正确、至少两个假设、无未解析 Evidence ID；任一不满足即不得标记 `SUCCESS`。
