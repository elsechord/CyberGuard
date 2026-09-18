# CyberGuard Skills（10 个可复用安全运营 Skill）

CyberGuard 的能力以 [AgentTeams](https://github.com/agentscope-ai/AgentTeams) Skill 形式交付：每个 Skill 是一个自包含的 `SKILL.md` 制品，定义**适用条件、输入、执行与安全边界、输出契约、失败语义**，由 Worker 按角色加载执行。领域无关的治理约束（只读面、审批门、独立复测）内嵌在 Skill 契约中，而不是依赖提示词自律。

## 版本总表（当前发布）

| Skill | 版本 | 职能 | 主要使用者 |
| --- | --- | --- | --- |
| alert-triage | 1.1.0 | 告警融合与初始分级 | alert-fusion |
| threat-intel-enrichment | 1.1.0 | 情报富化与 IOC 关联 | threat-intel |
| network-hunting | 1.1.0 | 网络侧狩猎 | network-hunter |
| endpoint-forensics | 1.1.0 | 终端取证 | endpoint-forensics |
| boundary-defense | 1.1.0 | 边界策略分析（出站面/放行面） | network-hunter |
| hypothesis-testing | 1.1.0 | 竞争性假设检验 | team-leader / 各调查 Worker |
| response-planning | **1.2.0** | 处置提案（只提案不执行；refuted 引用须入 contradicting_evidence_ids） | response-planner |
| controlled-response | 1.1.0 | 白名单受控执行（审批绑定） | controlled-responder |
| recovery-verification | **1.2.0** | 独立恢复核验（含实验室适配器） | recovery-verifier |
| incident-reporting | 1.1.0 | 证据引用化结案报告 | team-leader |

版本历史与变更细则见 [CHANGELOG.md](CHANGELOG.md)。

## 生命周期治理

1. **版本**：`SKILL.md` frontmatter `version` 字段为唯一权威；变更必须与 `CHANGELOG.md` 条目同提交（版本策略见 CHANGELOG）。
2. **分发**：`deploy/bootstrap-agentteams.sh` 打包并校验全部 Skills → 经 Matrix 向 Manager 发送哈希绑定的幂等请求 → 分发至七 Worker → 校验 Worker manifest（见 `agentteams/BOOTSTRAP.md` 的 Worker→Skills 映射表）。凭据不进入 Matrix 消息。
3. **运行版本记录（诚实边界）**：
   - v0.13.0 证据包运行（CG-2026-0002，2026-08-28/29）：全套 1.1.0 版本 Skills 经上述流程分发并执行（证据：release v0.13.0，2,992 条原生 Matrix 事件）。
   - run 009（AT-INV-20260918-009，2026-09-18）：**response-planning 1.2.0 与 recovery-verification 1.2.0 已在 AgentTeams Worker 上重新分发**（存量 Worker 经 `agt apply worker` 更新，zip 由当前仓库 skills/ 重建）。版本回读证实 Worker 加载版本与仓库一致：planner=response-planning 1.2.0、verifier=recovery-verification 1.2.0、investigator 的 endpoint-forensics/hypothesis-testing 为 1.1.0（与仓库版本表相符）。证据：`output/agentteams-native-20260918/run009/skill-version-readback-009.txt`、`skill-redistribution-009-workers.json`、`evidence-summary.md`。
4. **复用**：Skill 契约与 CyberGuard 服务解耦——`evidence.validate`、白名单与审批门对任何 AgentTeams 团队同样适用；跨团队复用时保持 `version` 字段与本仓库 CHANGELOG 对齐。

## 目录结构

```
skills/
├── README.md          # 本文件（索引 / 生命周期 / 运行版本记录）
├── CHANGELOG.md       # 版本变更记录
└── <skill-name>/
    └── SKILL.md       # Skill 制品（frontmatter: name / description / version）
```
