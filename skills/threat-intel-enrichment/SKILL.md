---
name: threat-intel-enrichment
description: 富集 IOC 并映射对手行为，控制来源、时效和共享基础设施偏差。
version: 1.1.0
---

# 威胁情报富集（Threat Intelligence Enrichment）

## 适用条件与依赖

用于已知 IP、域名、哈希、邮箱、证书或其他 IOC 的调查。依赖只读 MCP `intel.lookup`；情报只能辅助优先级和假设，不可取代事件遥测。

## 输入

`incident_id`、`scenario_id`、规范化 IOC、查询时间窗和可接受来源策略。IOC 未知或格式不合法时返回采集/清洗请求。

## 执行与安全边界

1. 对每个 IOC 调用 `intel.lookup`，记录来源、采集时间、first/last seen、置信度、标签、MCP 回执和 Evidence ID。
2. 显式标注共享主机、CDN、NAT、动态 IP、历史过期和单源偏差；信誉命中只支持风险排序，不证明当前入侵。
3. 只有底层事件证据支撑时才映射 MITRE ATT&CK；不要由 IOC 名称或厂商标签反推具体战术。
4. 为每个假设列出支持与反驳证据及下一步本地遥测需求。
5. 禁止编造情报来源、标签、活动组织、时间或 Evidence ID；禁止公开受许可限制的原始情报。

## 输出契约

输出 `enrichments[]`、`source_assessment[]`、`attack_mappings[]`、`hypothesis_impact[]`、`evidence_ids[]`、`ambiguities[]`、`recommended_local_checks[]`、`status`。

## 失败处理、复用与质量

情报服务不可用、无命中或来源不可信时输出 `PARTIAL/BLOCKED`，绝不以通用印象填补结果。结果可供告警研判和假设检验复用。质量门：来源与时间完整、共享基础设施风险已评估、ATT&CK 映射有底层证据、无虚构引用。
