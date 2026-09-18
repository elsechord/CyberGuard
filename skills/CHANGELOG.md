# Skills 版本变更记录

> 各 Skill 的当前版本以其 `SKILL.md` frontmatter 的 `version` 字段为准；本文件记录演进历史与发布口径。
> 分发机制与运行版本记录见 [README.md](README.md)。

格式遵循 Keep a Changelog；日期为提交进入本仓库的日期。

## [1.2.0] — 2026-09-18（决赛工程层，commit `2417da4`）

### recovery-verification 1.1.0 → 1.2.0
- 新增「执行模式与实验室适配器」一节：`lab_identity` 适配器要求 `run_id` + `action_id` 绑定，仅验证隔离身份服务中的目标账号禁用。
- 明确 `verification_scope` 语义：`simulated_response_contract` 只证明模拟契约；`point_in_time_lab_access` 仅表示观测时刻访问状态，不代表持续恢复或生产 SLO。
- 判定细则：执行回执 `applied` 不等于 `verified`；缺失探针 / 凭据错误 / 运行绑定不符 → `inconclusive`；真实观测与目标相反 → `failed`；通用 live connector 无专用核验契约时保持 `inconclusive`。
- 注：本版本随仓库发布；按 Skill 自身要求，须在下次 AgentTeams 分发时重新加载并保留调用证据（见 README「运行版本记录」）。

## [1.1.0] — 2026-08（复赛基线，commit `9b2bbe6`）

### 全部 10 个 Skill 首次随仓库发布
alert-triage / boundary-defense / controlled-response / endpoint-forensics / hypothesis-testing / incident-reporting / network-hunting / recovery-verification / response-planning / threat-intel-enrichment

- 每个 Skill 定义：适用条件与依赖、输入、执行与安全边界、输出契约、失败处理与复用边界。
- v1.1.0 为首个随本仓库公开发布的版本（版本号自内部草案延续，1.0.x 未随仓库发布）。
- 输入输出引用 Evidence 1.0 契约（OCSF 对齐事件类、STIX 2.1 观测类型、ATT&CK 映射）；输出契约显式声明失败语义（fail-closed）。

## 版本策略

- **补丁号（x.y.Z）**：文字勘误、示例修正，不改变输入输出契约。
- **次版本（x.Y.0）**：新增适配器 / 判定细则 / 新增可选输入，保持向后兼容。
- **主版本（X.0.0）**：输出契约破坏性变更（尚未发生）。
- 发布规则：版本变更必须与本文件条目同时提交；分发后须在 README「运行版本记录」中登记加载证据。
