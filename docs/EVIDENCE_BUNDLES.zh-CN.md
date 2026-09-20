# 采集 Linux 只读证据包

[English](EVIDENCE_BUNDLES.md) · [中文文档导航](README.zh-CN.md)

采集器生成调查输入，不直接给出安全结论。它只使用 Python 标准库，不执行文件中的命令、不启动 shell、不读取进程环境或命令行参数，不更改系统配置，也不连接外部服务。

## 采集

在待调查 Linux 主机或容器上，以需要记录访问范围的账户运行。默认读取当前可见的进程命名空间，以及采集器所在网络命名空间的 TCP／UDP 信息，不递归扫描日志、家目录、凭据或 `/etc`。

```sh
python scripts/collect-linux-evidence.py --output /tmp/cyberguard-evidence.json

# 显式选择额外来源；这些路径仅为示例
python scripts/collect-linux-evidence.py \
  --config /etc/systemd/system/example.service \
  --config /etc/cron.d/example \
  --log /var/log/auth.log \
  --sample-seconds 0.5 \
  --output /tmp/cyberguard-evidence-with-logs.json
```

输出文件不会被覆盖，可能含主机名、用户标识、IP 和运行细节。日志仅在明确指定后读取；已知 token／密码赋值、HTTP 凭据及 Authorization 值会脱敏，含可识别私钥内容的文件不会作为文本收集。脱敏是尽力处理，不是通用 DLP；共享给其他团队或模型前应检查或预先脱敏日志。

隔离测试可用 `--proc-root /path/to/proc-fixture`，只读取指定进程树，并把来源标为 `exercise`。采集器不会自行判定进程善恶，也不会启动 CPU 压测或挖矿负载。

## 数据格式

顶层 schema 为 `cyberguard-evidence-bundle/v1`。

| 字段 | 含义 |
| --- | --- |
| `bundle_id`、`created_at` | 唯一 ID 与带时区的生成时间 |
| `provenance.kind` | `live_collection`、`exercise` 或 `import`，由生产方填写，不代表来源已认证 |
| `artifacts` | 分别带哈希的证据记录 |
| `bundle_sha256` | 去掉自身字段后计算的顶层 SHA256 |

每份 artifact 包含 `evidence_id`、`kind`、字符串 `source`、`collected_at`、`observed_at`、`status`（`collected` / `unavailable`）、对象 `data` 和 `sha256`。计算 artifact 哈希时仅移除其自身 `sha256`；两级哈希均使用 UTF-8 JSON，参数为 `sort_keys=True, ensure_ascii=False, separators=(',', ':')`，仅接受有限数值。包哈希包含内部 artifact 哈希。

哈希用于发现相对已记录摘要的变化，不认证采集者，不证明主机未被控制，也不证明生产方主张真实。跨系统导入时保留原包。

| kind | 内容与范围 |
| --- | --- |
| `processes` | PID、PPID、可读取的真实 UID、comm、可读取的 executable 链接、starttime_ticks 和 CPU 观测；两次采样必须匹配同一身份。不读 cmdline/environ。 |
| `network` | 每个 `/proc/net/{tcp,tcp6,udp,udp6}` 一份，含端点、十六进制内核状态、inode、尽力匹配的 owner_pids。空归属表示未知，不表示不存在进程。 |
| `persistence` | 每个所选文件一份；解析 systemd ExecStart/Pre/Post 或 cron 的可执行项，省略参数。`enabled:null` 表示文件存在不等于已启用。 |
| `auth_logs` | 每个所选日志一份，包含从 1 开始的行号与脱敏文本，不推断攻击者、入口或组织归因。 |

所有类型都有 coverage。失败来源记录 reason，不会伪装成成功空结果。空文件或 socket 表只说明当时所选读取没有条目，不证明系统干净。未请求的日志与持久化来源标为 `unavailable/not_requested`。

CPU 是短窗口内的核心利用率估计，不证明挖矿。采集不是原子快照：进程消失、PID／网络命名空间、hidepid、权限、文件描述符复用都会限制覆盖。采集器没有 eBPF、容器逃逸、历史重建、二进制恶意分类或组织归因能力。systemd 展开、shell 包装、cron 环境与实际启用状态不在解析范围内。

## 导入 API

```python
from cyberguard_investigation.evidence import make_artifact, make_bundle, load_bundle, validate_bundle
from cyberguard_investigation.collector import collect_linux

bundle = load_bundle("/tmp/cyberguard-evidence.json")
validate_bundle(bundle)  # 成功返回 bundle；结构或完整性错误抛出 ValueError
```

`make_artifact(kind, source, data, *, status='collected', observed_at=None, collected_at=None)` 创建单份记录；`make_bundle(artifacts, *, provenance, bundle_id=None)` 创建包。调用者可以使用其他已定义类型；包验证器检查 JSON 结构与完整性，不将任意应用数据视为已验证语义。

导入上限：输入／规范化包 8 MiB、2,048 份 artifact、单份规范化记录 256 KiB、深度 32、100,000 个 JSON 值。禁止重复对象键或 evidence ID，拒绝 NaN／Infinity、错误时间戳、不支持的字段和摘要不匹配。HTTP 导入也应保持这些限制；接收材料不等于授权执行材料内的命令或方案。

采集上限：512 个进程、每进程 256 个文件描述符、每表 512 个 socket／64 KiB、32 个显式文件、每文件 64 KiB、每日志 1,024 行，CPU 观察窗口 0.01–2 秒。截断写入 coverage。文件读取拒绝最终路径组件是符号链接及非普通文件；调用者应选择可信目录。读取过程中变化的文件不是事务级文件系统快照。

## 验证

```sh
python tests/test_investigation_evidence.py
```

测试覆盖重算外层哈希后的内部篡改、重复 ID／JSON 键、大小／深度／非有限数值限制、不可用来源、PID 复用、CPU／父进程／UID、socket 解码、敏感参数省略、日志脱敏和截断，以及非普通文件拒绝。
