# 导入 Suricata EVE 日志

[English](INGEST.md) · [中文文档导航](README.zh-CN.md)

`scripts/ingest-suricata.py` 将已有 IDS 日志接入与演练相同的证据流程：通过网关归一化模块生成 Evidence 1.0 记录，补充稳定实体／可观测对象 ID、STIX 类型、ATT&CK 检查和质量评分，按 `contracts/evidence.schema.json` 验证后追加到网关控制台读取的 `evidence.jsonl`。

## 处理范围

- 离线、只读读取 Suricata 导出的 EVE JSON／JSONL 文件，指定关联事件 ID。
- 真实数据进入相同质量流程，可在 `/console`、`/incidents` 与证据图中查看。
- 只追加记录，不改已有行；重复运行按内容 SHA256 跳过已导入事件。
- 默认转换 `event_type: alert`，保留内嵌 HTTP／DNS／TLS 上下文。默认跳过 stats 与非告警摘要；`--include-flows` 额外转换 flow。
- ATT&CK 只依据脚本 `ATTACK_HINTS` 中有限、公开的关键词表推导。无可靠映射时保留空列表及 `no_attack_mapping` 问题，不编造技术编号。
- Suricata severity 到 confidence 的映射为：1 → 0.9、2 → 0.75、3 → 0.6、未知 → 0.5。

脚本不修改 Evidence 1.0 契约、网关代码或已有证据。它读取已有文件，不是实时 SIEM／EDR 连接器；在线接口见[厂商连接器](LIVE_CONNECTORS.zh-CN.md)。无法识别的签名保留原 signature/category 文本及对应质量结果。

## 使用命令

```bash
# 只验证，不写入
python scripts/ingest-suricata.py \
  --input /var/log/suricata/eve.json --incident CG-SURICATA-001 \
  --data-dir ./data --dry-run

# 导入告警和 flow，并推进事件工作流
python scripts/ingest-suricata.py \
  --input /var/log/suricata/eve.json --incident CG-SURICATA-001 \
  --data-dir ./data --include-flows --workflow
```

| 参数 | 含义 |
| --- | --- |
| `--input` | 文件，或包含 `*.json` / `*.jsonl` 的目录，可重复指定 |
| `--incident` | 事件 ID，例如 `CG-SURICATA-001` |
| `--data-dir` | 网关实际读取的数据目录 |
| `--dry-run` | 只转换与验证，不写入 |
| `--include-flows` | 额外导入 flow |
| `--workflow` | 为 `ingest-suricata` 会话记录 received → investigating |
| `--sensor` | 上报设备实体，默认 `suricata-sensor` |
| `--environment` | 真实导出用 `live`，规范示例用 `fixture` |

脚本输出 JSON 汇总，包括读取行数、转换／跳过数量、质量分布、实体／可观测对象数量及映射的技术。

## 用仓库样例体验

```bash
# 导入样例，明确标为 fixture
python scripts/ingest-suricata.py \
  --input samples/suricata/eve-sample.jsonl --incident CG-SURICATA-001 \
  --data-dir ./data --environment fixture --workflow

# 启动读取该目录的本机网关
CYBERGUARD_API_TOKEN=dev-token CYBERGUARD_SCENARIO_DIR=./scenarios \
CYBERGUARD_DATA_DIR=./data CYBERGUARD_ACTION_AUDIT_FILE=./data/actions.jsonl \
uvicorn app.main:app --app-dir services/security-tool-gateway --host 127.0.0.1 --port 18100
```

另开终端执行：

```bash
curl -H "Authorization: Bearer dev-token" http://127.0.0.1:18100/incidents
```

浏览器打开 <http://127.0.0.1:18100/console> 查看 `CG-SURICATA-001`。`dev-token` 仅用于本机演练。

样例混合了 Suricata 官方用户指南中的原始示例和按公开 EVE schema 合成的记录，来源表见 [samples/suricata/README.md](../samples/suricata/README.md)。它不是某次真实入侵的捕获数据。

## 后续接入

EVE 适配展示文件接入的通用流程：复用归一化、校验契约、只追加、保持幂等。其他商业 SIEM／EDR 的专用连接器需要逐一实现和验证，可基于[现有在线连接机制](LIVE_CONNECTORS.zh-CN.md)扩展。
