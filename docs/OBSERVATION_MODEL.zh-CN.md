# 安全观测与证据模型

[English](OBSERVATION_MODEL.md) · [中文文档导航](README.zh-CN.md)

CyberGuard 在 Agent 引用前，将 SIEM、威胁情报、NDR、EDR／运行时、CMDB 和恢复记录归一化为带哈希绑定的 Evidence。原生数据保留在 `data`，归一化补充关联和质量元数据，不重写原始观测。

## 标准兼容范围

- `standard.alignment.event_profile` 使用 **OCSF-aligned**，表示借鉴其分类，不声明正式 OCSF 符合性；保留厂商原始字段。
- 网络指标使用 STIX 2.1 的可观测对象词汇，如 `ipv4-addr`、`ipv6-addr`、`domain-name`、`url`。字段定义以 [STIX 2.1 标准](https://docs.oasis-open.org/cti/stix/v2.1/stix-v2.1.html)为准。
- 对手行为映射到格式合法的 MITRE ATT&CK 技术／子技术 ID，不把语法检查当成行为归因。ATT&CK v18 已弃用旧 Data Sources，覆盖规划应参考当前 Data Components；参见[官方说明](https://attack.mitre.org/datasources/)。

## Evidence 1.0 字段

| 字段 | 用途 |
| --- | --- |
| `sha256` | 规范化原生连接器记录的 SHA256 |
| `standard.raw_sha256` | 将归一化元数据绑定回原生记录 |
| `entities` | 账户、设备、工作负载、服务、命名空间、镜像、进程等带类型稳定 ID |
| `observables` | 稳定 ID、STIX 兼容类型与原生值 |
| `attack_techniques` | 合法技术／子技术 ID，排除并报告非法值 |
| `quality` | 确定性分数、pass/review、问题及必填字段完整性 |

稳定 ID 来自规范化类型和大小写折叠值的 SHA256。因此 EDR 的 `host=FIN-LT-023` 可与 NDR 的 `src_host=fin-lt-023` 关联，不依赖厂商字段名。原始值仍属于受限证据，公开前需脱敏。

## 质量检查

评分组成：必填字段 50%（source、kind、summary、对象 data 和有界 confidence）；合法观测时间 15%；可关联实体／可观测对象 15%；支持或反驳至少一个假设 10%；有效 ATT&CK 映射 10%。

分数 ≥ 0.7 为 pass。演练材料保留 review 元数据；真实连接器低于 `CYBERGUARD_MIN_EVIDENCE_QUALITY` 的记录在持久化前拒绝。事件接口 `/incidents/{id}/quality` 只有在至少三个独立来源、且全部记录不低于 0.7 时通过。

该分数衡量可用性，不证明事实真实。confidence 仍是适配器的可靠性评估，假设可以冲突；review 状态应促使调查补充材料。

## 关联图

`/incidents/{id}/graph` 提供来源、证据、实体、可观测对象、ATT&CK、假设、事件和响应动作节点。共同稳定 ID 将多来源重复提及变成可检查的关联。事件摘要展示实体数、跨来源实体数、ATT&CK 覆盖、平均质量与 review 数量，可区分真实数据关联和只并排展示多份聊天。

## 新适配器验收

1. 目标地址、路径与凭据由服务端管理。
2. 来源身份和处理密级由服务端决定，不接受上游覆盖。
3. 提供 ISO 8601 `observed_at` 并说明时区处理。
4. 映射至少一个支持的实体／可观测字段，保留原始载荷。
5. 关联有范围限制的假设，只映射有依据的 ATT&CK 技术。
6. 添加能证明归一化、原始哈希、质量行为与跨来源身份的 fixture。
7. 验证错误时间、非法技术 ID、超大响应与上游故障路径。
