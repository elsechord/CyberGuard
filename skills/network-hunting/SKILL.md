---
name: network-hunting
description: 以假设驱动方式调查网络流、DNS、TLS 与 HTTP 证据，并显式说明遥测缺口。
version: 1.1.0
---

# 网络狩猎（Network Hunting）

## 适用条件与依赖

用于已有账号、主机、IP、域名、哈希或时间窗的网络调查。依赖只读 MCP `network.search`；边界策略判断须交由 boundary-defense 的 `boundary.policy` 交叉验证。

## 输入

`incident_id`、`scenario_id`、至少一个已知实体、受限时间窗、调查假设（可选）。没有实体或时间窗时先请求告警研判补全。

## 执行与安全边界

1. 调用 `network.search`，保存完整调用回执及 Evidence ID；仅报告回执实际返回的源/目的、协议、时间和统计字段。
2. 分析方向、体量、周期性、首次/末次观测、基线或新颖性，并为每项判断标示证据与置信度。
3. 加密、异地登录、罕见端口或单条流量均只是线索；不得单独判定恶意、VPN 类型、端口开放、隧道、规则名称或攻击者身份。
4. 明确支持/反驳的假设及缺失遥测；禁止越出事件范围请求抓包或扩展性扫描。
5. 禁止从题面生成 IP、端口、流量大小、时间戳、DNS/TLS 细节或 Evidence ID。

## 输出契约

输出 `observed_flows[]`、`entities[]`、`baseline_assessment`、`hypotheses[]`、`evidence_ids[]`、`missing_telemetry[]`、`next_queries[]`、`status`。

## 失败处理、复用与质量

无结果不等于无流量；区分空集、遥测盲区和工具失败。输出 `PARTIAL/BLOCKED` 与具体采集建议。结果可供边界防御、假设检验和响应规划复用。质量门：所有网络细节来自回执、时间窗有界、无未解析 Evidence ID、结论与原始数据强度匹配。
