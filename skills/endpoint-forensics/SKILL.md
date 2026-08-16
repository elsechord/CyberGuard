---
name: endpoint-forensics
description: 基于端点进程、文件、身份和持久化证据构建可复核时间线。
version: 1.1.0
---

# 终端取证（Endpoint Forensics）

## 适用条件与依赖

用于调查主机、工作负载或账号可能关联的端点活动。依赖只读 MCP `endpoint.timeline`，必要时以 `asset.context` 识别资产；不得以其他 Agent 的叙述替代端点证据。

## 输入

`incident_id`、`scenario_id`、主机/账号/文件哈希等实体、受限时间窗。未知端点实体时先请求告警研判补全。

## 执行与安全边界

1. 调用 `endpoint.timeline`，保存 MCP 回执的 Evidence ID、观察时间、来源和质量。
2. 按观察时间排序，重建父子进程关系，识别用户上下文、完整性级别、命令来源、持久化、凭据访问和暂存行为。
3. 将原始事实、解释、假设和缺口分开；“未返回数据”只能说明不可判定，不能推出已失陷或已持久化。
4. 仅在端点证据与至少一个独立来源相互印证时才建议隔离；不在聊天室披露受限文件内容。
5. 禁止构造进程树、命令行、文件路径、时间戳或 Evidence ID。

## 输出契约

输出 `timeline[]`、`process_lineage[]`、`confirmed_facts[]`、`interpretations[]`、`hypotheses[]`、`cross_source_requirements[]`、`containment_recommendation|none`、`evidence_gaps[]`、`status`。

## 失败处理、复用与质量

端点遥测缺失、保留期不足或工具失败时标记 `PARTIAL/BLOCKED` 并提出采集请求。结果可供假设检验和响应规划复用。质量门：每项事实可定位到端点回执、解释不伪装为事实、隔离建议有独立佐证。
