# AgentTeams 原生调查任务服务

首次安装请走 [从零部署指南](NATIVE_INSTALL.md)：包含固定版本构建、私有模型配置、团队创建、兼容层安装与重启、Console 连接、预算开启及第一案验证。

默认后端为 `native`，要求 AgentTeams v1.2.3 的 Project workflow API 和启用 TeamHarness 的团队。调用方 Agent 提交材料；AgentTeams 负责调查。Console 不再按固定 investigator → planner → verifier 顺序驱动聊天。

## 调度过程

1. Console 持久化请求，创建确定性 ID 的原生 Project。
2. 通过 Matrix 向 Leader 发送一次请求，重试使用同一事务 ID。
3. Leader 使用 TeamHarness 规划 DAG、自行选择 Worker 和中间步骤；调查与独立复核分配给不同 Worker。
4. Worker 通过原生 ack / submit 提交任务，Leader 验收结果。
5. 全部节点已验收且报告有效后，如 Project 仍为 active，Console 调用官方 `/complete` 接口收尾，再重新读取完成状态。
6. Console 查询 `/api/v1/projects/{id}/workflow?includeTasks=true&team=...`，显示节点状态；从 Task artifact API 获取已发布的 `report.json`，验证材料引用后交付。

完成依据为原生节点状态及实际文件，不解析聊天中的“已完成”。Console 不再设置每角色 300 秒期限。缺失连接时保留任务等待恢复。取消调用 Project pause，阻止后续调度；AgentTeams 允许正在执行的任务完成。

## 配置

以下变量配置在 Console 服务端，凭据不进入 Skill 提示词：

| 变量（前缀 `CYBERGUARD_AGENTTEAMS_`） | 用途 |
| --- | --- |
| `BACKEND` | `native`（默认）；`matrix` 为旧串行兼容模式 |
| `CONTROLLER_URL` | 可达 Controller，例如 Docker 网络内 `http://agentteams-controller:8090`；依实际端口配置 |
| `CONTROLLER_TOKEN` | Controller bearer 凭据 |
| `TEAM_ID` | 原生团队 ID |
| `LEADER_ROOM_ID` / `LEADER_USER_ID` | Leader 的 Matrix 房间及用户 ID |
| `MATRIX_URL` / `MATRIX_TOKEN` | Matrix 地址及持久 bearer 凭据 |
| `MATRIX_HOST` | 可选虚拟 Host |

Leader 需要原生 TeamHarness/WorkerFlow 工具及可用 Worker。Console 为新案件直接准备私有任务房间（原生 TASK 命名、room.meta 标记），读取原生 Team 成员的 Matrix ID 并一次邀请整个团队；完整请求只提及 Leader。Leader 在当前任务房间规划、委派和接收完成事件，无需额外建房或跨房间摘要交接。房间准备由 Console 执行，任务规划与验收仍使用原生工具。Matrix 身份须可创建房间和上传媒体。只创建 Project 不会自动启动调度，必须发送完整 Leader 请求。创建 Project 时不填回执地址，以免 v1.2.3 的“项目已创建”通知先唤醒 Leader。不要像旧的无工具验证环境那样禁用所有 MCP 和内建工具。

部署文件位于 `deploy/investigation-service/`：`build-controller.sh` 固定 v1.2.3 上游提交，保留 Worker 自动端口绑定到 loopback 的补丁；`compose.native.yaml` 用于新主机，`native-controller.override.yaml` 用于已有本地实例升级。`prepare-native-team.py` 接受 `--plan`、`--private-dir`、`--model-env`、`--run-id` 与 `--name-prefix`；`configure-native-team.py` 从当前安装的管理员配置生成独立 Matrix 身份凭据。升级前保留原 Controller 数据备份。

可选 Model Guard 支持 `tool_policy: "runtime"`：负责模型身份与费用限额，工具授权交由 AgentTeams。不会因为新增工具声明或重复工具报错关闭整个调查服务。默认 `guard` 模式继续适用于旧的固定工具策略部署。

## 范围与恢复

原始材料与提交者解释分别传递，产物保留材料 ID 和逐字引用。原生任务状态不证明推理绝对正确；报告仍呈现未知项。调查提交不授权响应动作。

原始材料和报告格式通过 Matrix 媒体 API 作为 `case.json` 传递，聊天只发送该文件的 URI 和调查要求。所有参与 Worker 必须先运行 `install-collaboration.py` 安装 `case_packet.py`，并具备现有 Matrix URL/身份配置。Worker 用 `fetch` 下载原始字节、验证哈希，用 `check` 在提交前检查报告格式和逐字引用；避免模型转抄材料或哈希。

当前案件包仍限 60 KiB，超过时明确返回 `materials_too_large`。API 的更大接收上限不代表原生传输可承载大文件。PDF/Office 解析和大型证据包传输尚未接入。Matrix 媒体 URI 本身不提供按租户隔离，适用于当前受信单组织部署。

本地持久化 Project ID、Matrix event ID 和原生工作流快照。重试复用 Project 与事务 ID；已有的旧串行任务继续由旧后端完成，不在中途转换协议。共享团队适合单组织本地部署；不同客户需要独立团队/上下文配置。

运行记录见 [验证记录](INVESTIGATION_SERVICE_VALIDATION.md)。旧协议和旧测试记录见 [Matrix 串行后端](AGENTTEAMS_MATRIX_LEGACY.md)。

参考：[AgentTeams 官方项目](https://github.com/agentscope-ai/AgentTeams)、[v1.2.3 发布](https://github.com/agentscope-ai/AgentTeams/releases/tag/v1.2.3)。


## 按需展开临时专家

在原生团队上运行 `deploy/investigation-service/install-collaboration.py` 安装协作 Skill、三种模板和本机 helper。已有三个团队成员不变；调查 Worker 根据问题选择直接调查，或使用 WorkerFlow 展开临时专家。团队 Task 与临时 Agent 是两个层级。

每个专家关联调查问题与原始材料 ID。使用原生 `submit_to_agent` / `chat_with_agent` / `check_agent_task` 交互，由所属 Worker 汇总。独立复核仍分配给另一个 TeamHarness Worker。完成或失败后通过原生清理回收实例，保留共享成果；启动中的删除冲突做有界重试。

Console 每隔至少 15 秒尝试读取已分配 Task 的 `collaboration.json`，展示可用的原生状态快照。没有这份可选产物的旧任务正常运行。原始工作流、全部模型上下文与凭据不放入该快照。正常完成和失败支持回收；Project pause 后在途内部任务仍由所属 Worker 收尾，本轮没有增加独立清理守护进程。

[调研与设计取舍](ADAPTIVE_AGENT_RESEARCH.md) · [计划格式与 CLI](../deploy/investigation-service/collaboration/README.md)
