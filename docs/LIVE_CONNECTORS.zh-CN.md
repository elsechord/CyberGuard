# 接入现有安全系统

[English](LIVE_CONNECTORS.md) · [中文文档导航](README.zh-CN.md)

仓库演练不要求外部安全产品。接入真实遥测时，将 `config/connectors.json.example` 复制为 `config/connectors.json`，按实际服务修改固定路径，并在 `.env` 填写对应 base URL 和凭据。示例包含 SIEM、NDR、防火墙／网关、EDR 和 CMDB 适配入口。

Agent 仍调用同一套工具，使用 `scenario_id: live`。Agent 可以提供查询参数，但不能指定上游地址、认证头或秘密；这些由网关从只读配置与环境加载。

证据的 `source`、`handling` 也由服务端连接器定义。同名上游字段会被覆盖，避免上游伪造独立来源数量或降低材料密级。

## 返回数据格式

连接器可以返回厂商原生 JSON，CyberGuard 会将它包装为受限证据。建议在适配接口返回：

```json
{
  "source": "wazuh-indexer",
  "kind": "alert_bundle",
  "summary": "发现三条关联的认证告警。",
  "data": {"alerts": []},
  "confidence": 0.86,
  "attack_techniques": ["T1078"],
  "supports": ["H1-credential-compromise"],
  "contradicts": [],
  "handling": "restricted",
  "observed_at": "2026-08-13T01:12:00Z"
}
```

网关补充 Evidence 1.0 标准元数据、稳定实体／可观测对象 ID 和确定性的质量结果。真实来源记录低于 `CYBERGUARD_MIN_EVIDENCE_QUALITY`（默认 0.7）会在进入事件账本前被拒绝。字段机制见[安全观测模型](OBSERVATION_MODEL.md)。

上游字符串仍是数据，不是 Agent 指令。只有适配器说明置信分数含义时，才应使用上游的 confidence 数值。

## 传输与查询约束

- 默认要求 HTTPS；私有实验网络可设置 `CYBERGUARD_ALLOW_INSECURE_HTTP=1`。
- 连接器路径在服务端固定，不得包含 `..`；URL 中不能嵌入凭据。
- 上游响应最多 2 MB，超时 30 秒。
- GET 连接器拒绝 Agent 自带参数，避免不受约束地拼接查询字符串。搜索需求应使用限制参数范围的 POST 适配接口。

## 厂商适配方式

如果厂商查询格式不同，可以在网关旁部署薄适配层：

```text
CyberGuard Agent → 固定工具接口 → 适配器 → 厂商 API
                                  └─ 统一时间、实体与处理密级
```

适配器凭据保存在自己的秘密管理系统或 Higress。启用新来源前补齐接口样例和测试。这个机制不等于已经提供所有厂商的开箱即用连接器；已有导出文件可先用[Suricata 导入](INGEST.zh-CN.md)或[调查材料提交](INVESTIGATION_TASKS.md)。
