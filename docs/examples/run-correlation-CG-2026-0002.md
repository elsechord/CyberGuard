# Run 关联视图 — CG-2026-0002

- 生成时间：2026-09-18T13:12:56.866465+00:00
- 数据目录：`../tmp/console-demo-data`（evidence 6/6 条在范围内，workflow 4 条）
- run 范围：事件级（未指定 run_id）；证据未记录 run 绑定
- 证据完整性：6/6 envelope 校验通过（valid）

## 时间线（工作流 × 证据采集）

| 时间 (UTC) | 类别 | 角色/来源 | 变迁 / Evidence | 说明 | 质量 | ATT&CK |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-18T09:07:50Z | evidence | siem | alert_bundle `EV-1642973790b3` | A production workload executed a shell from the web process shortly after an unsigned image dep… | 1.000 | T1059.004, T1195.002 |
| 2026-09-18T09:07:51Z | evidence | threat-intel | ioc_enrichment `EV-8a67a367d1b0` | The destination domain is newly registered and has weak malware-family association. | 1.000 | T1071.001 |
| 2026-09-18T09:07:51Z | evidence | network-sensor | network_flow `EV-d1e226aae8c9` | The checkout Pod established periodic TLS sessions to a destination never observed in the names… | 1.000 | T1071.001 |
| 2026-09-18T09:07:51Z | evidence | kubernetes-egress-gateway | boundary_policy_snapshot `EV-b852eff043b6` | A wildcard HTTPS egress rule permits the production workload to reach the suspicious domain and… | 1.000 | T1071.001 |
| 2026-09-18T09:07:51Z | evidence | runtime-security | container_timeline `EV-de6330002381` | The suspicious binary was present in the image layer before the container started, favoring sup… | 1.000 | T1059.004, T1195.002 |
| 2026-09-18T09:07:52Z | evidence | cmdb-and-ci | asset_context `EV-624f56d0ceba` | The deployment used a CI service token outside the normal release window and bypassed signature… | 1.000 | T1078, T1195.002 |
| 2026-09-18T09:08:06Z | workflow | manager | ∅ → received |  | — | — |
| 2026-09-18T09:08:28Z | workflow | team-leader | received → investigating | 四线证据已收齐，竞争性假设更新 | — | — |
| 2026-09-18T09:08:40Z | workflow | team-leader | investigating → evidence_validation | evidence gate passed | — | — |
| 2026-09-18T09:08:40Z | workflow | response-planner | evidence_validation → awaiting_approval（需人工审批） | 提案：禁用受感染账号，等待人工审批 | — | — |

## 指标汇总

- 证据：6 条，独立来源 6 个（cmdb-and-ci, kubernetes-egress-gateway, network-sensor, runtime-security, siem, threat-intel）
- 质量：均值 1.0 / 最低 1.0；review 门 0 条
- ATT&CK：T1059.004, T1071.001, T1078, T1195.002
- 实体：11 个，其中跨源印证 1 个
- 工作流会话 `soc-demo`：4 次变迁，终态 `awaiting_approval`（未决人工审批等待）

## 证据完整性

| Evidence ID | Envelope SHA-256 | 状态 |
| --- | --- | --- |
| `EV-1642973790b3` | `ffeac7756cdfb17f9a72648342682079c0bf5a9f81468ca4f2334a40a8489976` | valid |
| `EV-8a67a367d1b0` | `ec04881c88c760a434171579352113a17221a32a0b3ef665ea4476d389efcddd` | valid |
| `EV-d1e226aae8c9` | `b2479621892ba14c60443ce8a99e9c98778f753b3cc742838600b8b5dff59dbf` | valid |
| `EV-b852eff043b6` | `7cb56a9d61f30bfe1e53edab22efe8ddab43c4da7fe09e7b381ba9fd1d677910` | valid |
| `EV-de6330002381` | `07fd39b0df5b6fff306765f567576a22074a46e3da6cad7090057524e3dcc1d6` | valid |
| `EV-624f56d0ceba` | `4856c6cd462c646bee7762017ebef31b66883c81f63368a467e163df05e7f9da` | valid |

## 链接位（审计链与复现材料）

- 网关 run 导出（证据 + 经认证行动事件 + export_sha256）：`GET /incidents/CG-2026-0002/runs/<run_id>`
- 执行器审计链（审批/执行/回滚事件）：`GET /audit/incidents/CG-2026-0002/events?run_id=<run_id>（CYBERGUARD_AUDIT_VERIFY_URL，需审计读者凭据）`
- 控制台 run 视图：`/console`
- 原生 AgentTeams/Matrix 任务事件（不在本视图范围）：`docs/LIVE_TASK_EVIDENCE.md · v0.13.0 参考包 webshell-20260828T163202Z.tar.gz + .sha256`

## 边界（诚实声明）

1. 本视图离线读取网关数据目录（evidence.jsonl / workflow.jsonl），只关联网关侧证据与工作流；
2. 行动/审批/回滚事件以执行器认证导出为准，本视图仅提供链接位；
3. workflow 事件按 incident/session 记录且不携带 run_id，run 过滤仅作用于证据；
4. 原生 Matrix/AgentTeams 任务事件（Task、Worker、Skill 调用及版本、模型 usage）不在覆盖范围，见 docs/LIVE_TASK_EVIDENCE.md。

导出摘要 `export_sha256`：`fc249f00bdd4548917a5a31478bbdddd02e0b34e752b4804aeb78defdee6b46b`（覆盖除自身外全部字段）
