# CyberGuard 中文文档

从安装、提交材料到接入已有系统，可以按下面顺序使用。带「英文历史记录」标记的文档用于还原早期实验，不作为当前安装步骤。

## 第一次使用

| 目标 | 文档 |
| --- | --- |
| 在网页填写模型并初始化团队 | [网页安装向导](WEB_ONBOARDING.zh-CN.md) |
| 按命令行部署完整 AgentTeams 服务 | [原生安装指南](NATIVE_INSTALL.md) |
| 先启动基础服务并采集第一份证据 | [快速开始](QUICKSTART.zh-CN.md) |
| 创建管理员、理解角色和 API Key | [控制台使用](OPERATIONS_CONSOLE.zh-CN.md) |
| 提交调查、查看进度、取回报告 | [调查任务](INVESTIGATION_TASKS.md) |
| 在 Codex、Claude Code 或已有 Agent 中使用 | [Skill 安装与连接](EXTERNAL_AGENT_SKILL.md) |

## 接入数据与开发扩展

| 目标 | 文档 |
| --- | --- |
| 从 Linux 主机采集只读材料 | [证据包采集与导入 API](EVIDENCE_BUNDLES.zh-CN.md) |
| 导入 Suricata EVE 文件 | [日志导入](INGEST.zh-CN.md) |
| 对接安全厂商／防火墙／EDR 等接口 | [在线连接器](LIVE_CONNECTORS.zh-CN.md) |
| 理解规范化字段、质量检查与关联 | [观测模型](OBSERVATION_MODEL.zh-CN.md) |
| 连接 Controller、Matrix 与原生 Task | [AgentTeams 任务服务](AGENTTEAMS_TASK_SERVICE.md) |
| 理解调用方与后台的身份边界 | [Agent 身份](AGENT_IDENTITY.md) |
| 理解调查组件与材料链路 | [调查流程](INVESTIGATION_PIPELINE.md) |
| 查找后台角色 Skill | [Skill 目录](SKILL_CATALOG.md) |

已有中文的原生安装、Skill 与任务文档保持原路径；英文原版新增的中文译本使用 `.zh-CN.md`，并在两侧提供语言链接。

## 运维与发布

- [部署、升级、备份和迁移](OPERATIONS_DEPLOY.zh-CN.md)
- [日常运维及历史基础验收](OPERATIONS.zh-CN.md)
- [模型预算、身份与调用限制](MODEL_GUARD.zh-CN.md)
- [威胁模型](THREAT_MODEL.zh-CN.md)
- [发布流程](RELEASE.zh-CN.md)

## 演示与验证证据

- [网页安装向导验收](validation/onboarding/README.md)：首次管理员、模型连接、私有配置保存和重启恢复。
- [决赛入口](FINALS_ENTRY.md)与[一页亮点证据](PROVEN_CAPABILITIES.md)
- [完整案件验证](FULL_CASE_VALIDATION.md)、[干净目录部署记录](validation/clean-install/README.md)
- [实时处置闭环](LIVE_RESPONSE_DEMO.md)、[Linux 持久化实验](HOST_LAB.md)
- [演示与录制步骤](JUDGE_DEMO.md)
- [按需专家与双向通信](ADAPTIVE_COLLABORATION_VALIDATION.md)
- [基础处置生命周期实验](LAB_EXECUTION.zh-CN.md)
- [调查评测](INVESTIGATION_EVALUATION.zh-CN.md)

## 设计与历史记录

当前设计调研：[接入设计](AGENT_ONBOARDING_RESEARCH.md)、[调查基础设施](INVESTIGATION_INFRA_RESEARCH.md)、[动态协作](ADAPTIVE_AGENT_RESEARCH.md)。这些是设计依据，不替代运行验收。

以下保留英文历史正文，**不是完整中文覆盖范围**：

| 历史记录 | 内容 |
| --- | --- |
| [AGENTTEAMS_LOCAL](AGENTTEAMS_LOCAL.md) | 早期本地部署 |
| [AGENTTEAMS_GUARDED_LOCAL](AGENTTEAMS_GUARDED_LOCAL.md) | 早期受预算控制的本地串行实验 |
| [AGENTTEAMS_INVESTIGATION](AGENTTEAMS_INVESTIGATION.md) | 早期调查集成 |
| [AGENTTEAMS_MATRIX_LEGACY](AGENTTEAMS_MATRIX_LEGACY.md) | 已被原生 Task 替代的串行 Matrix 协议 |
| [AGENTTEAMS_RECOVERY_PLAN](AGENTTEAMS_RECOVERY_PLAN.md) | 旧恢复计划 |
| [LIVE_TASK_EVIDENCE](LIVE_TASK_EVIDENCE.md) | 早期任务证据 |
| [COMPETITION](COMPETITION.md) | 早期比赛要求记录 |

历史文档可能包含当时的固定路径、版本或命令，当前部署请回到网页向导或原生安装指南。
