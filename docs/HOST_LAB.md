# Linux 持久化处置实验

本实验验证一个具体问题：**成功结束进程之后，工作负载可能被持久化机制重新启动；执行回执不等于恢复。**

这是本地 Docker 中真实的进程、文件、审批和探测实验。不是实际挖矿、真实入侵材料、LLM 推理评测，也没有运行 AgentTeams。编排脚本预先指定两次处置，不能据此宣称 Agent 自主发现了根因。恶意与正常进程使用同一份无害工作代码，单凭 CPU、文件名或程序哈希不能判定恶意。

## 一键复现

从仓库根目录运行（Docker Desktop 使用 Linux 容器）：

```sh
docker compose -f compose.host-lab.yaml up --build --abort-on-container-exit --exit-code-from host-lab
docker compose -f compose.host-lab.yaml cp host-lab:/artifacts/. artifacts/host-lab/
```

命令默认使用 **automated_lab_harness** 审批，只用于可重复的功能验收。输出中应先出现 `partial_cleanup_is_not_recovery`、`actual_process_restarted`，再出现 `bounded_recovery_and_control_progress`。失败返回非零退出码，并保留失败 manifest 与已收集 trace。

如需本人在终端审阅并批准两个具体动作：

```sh
docker compose -f compose.host-lab.yaml run --rm host-lab python scripts/host-lab-demo.py --interactive --output /artifacts
```

每次展示动作、目标引用、环境标识与不可逆属性，必须输入包含 action_id 的批准文字。拒绝或中断不会自动批准。此模式是本地操作员交互，尚未接入企业身份系统。

运行负面测试：

```sh
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=128m cyberguard/host-lab:local python tests/test_host_lab.py
```

## 实际行为与边界

|步骤|实际行为|验收|
|---|---|---|
|采集|从 Linux `/proc` 读取 PID、启动 ticks、父进程、命令行、解释器/worker 哈希；读取监督文件和真实进程事件|统一 Evidence ID、run_id 与内容哈希|
|第一次处置|明确批准后向精确的子进程发送 SIGTERM；监督文件保留|进程实际停止，随后被监督线程重启|
|第一次验证|只读凭据重新采样进程、持久化项、正常进程 heartbeat|判为 failed，不能根据 applied 回执宣布恢复|
|第二次处置|新提案、新审批，隔离指定版本监督文件并停止目标工作负载|持久化文件版本变化时拒绝；不给任意路径或 shell 权限|
|第二次验证|三次采样，间隔 1.1 秒，覆盖实验内 1 秒重启周期；正常进程 heartbeat 必须递增|仅给出有明确时间窗和范围的 verified|

进程引用绑定环境 UUID、PID、启动 ticks、解释器哈希和工作文件哈希；信号通过 Linux pidfd 发出。文件引用绑定环境 UUID 与内容哈希。审批后对象变化会产生 `execution_rejected`，不会自动换成新对象。实验后端只允许自身创建的 compute 工作负载，正常 control 进程不可处置。

复用现有 executor 的审批摘要绑定、HMAC 审计、dispatch intent 与只读 reconciliation。后端在变更前落盘 unknown intent；进程或后端异常中断时，不盲目重复副作用。终止进程无法恢复原有内存状态，所以两个动作标为不可逆，不提供虚假 rollback。

容器非 root、根文件系统只读、无外部网络、无宿主目录/容器 socket 挂载、无额外 capabilities。随机凭据分角色传递；调查/验证服务没有处置和审批密钥。实验的采集器与监督器仍共享可信边界，不声称可抵抗被控主机伪造遥测。

## 接口与后续 AgentTeams 接入

- `POST /tools/endpoint/timeline`：`scenario_id=lab_host`，必填 `run_id`，返回真实实验快照。
- `POST /actions/propose`：executor 配置 `CYBERGUARD_EXECUTION_MODE=host_lab`，仅允许 `terminate_process` 或 `disable_persistence`；`target` 来自快照中的 `target_ref`。
- 原有 approve/execute/audit API 不变；新增动作不允许退回 simulation 模式执行。
- `POST /tools/recovery/metrics`：`scenario_id=lab_host`、同一 `run_id`，`arguments.action_id` 指定已执行动作。审批前、跨 run、环境不一致、探测失败返回 inconclusive。
- `/incidents/CG-HOST-001/runs/{run_id}` 导出同一 run 内两次执行及 failed → verified 观察。导出是历史观察，不会自动重新探测。

`HostLabStack` 目前是本地集成测试/交互实验入口，不是生产服务启动器。后续接服务器时应让真实 AT 工作者选择调查步骤和处置建议，沿用这些 API；还需要打通 MCP 的 run_id、action 参数、真实人工审批与 AT Task/Worker/Skill 运行证据。当前脚本只构成固定工作流基线。

## 未完成的场景能力

尚未实现真实入侵入口复原、systemd/cron/Kubernetes 持久化采集、网络/矿池证据、跨主机调查、生产采集器、可信外部遥测、企业身份/多租户、长期存活服务与持久卷故障恢复。没有真实事件资料时不得伪造这些结论；尤其不能从矿工程序或公共矿池推导攻击组织。

本轮产物证明的是具体执行和验收机制能否工作，不是商业落地或差异化壁垒已经成立。下一阶段才是让模型处理未知变体，并在相同数据、工具、权限和预算下比较固定流程、单 Agent、多 Agent 的漏判、误处置、恢复率与成本。
