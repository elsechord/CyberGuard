# 模型调用预算与准入

[English](MODEL_GUARD.md) · [中文文档导航](README.zh-CN.md)

AgentTeams Worker 的独立 Higress 路由在访问付费模型前经过 Model Guard，先预留预算再发送请求，而不是调用结束后才统计。本组件是单进程本地服务，不是完整的多租户模型网关。

当前原生安装采用 `tool_policy=runtime`，操作入口见[网页部署向导](WEB_ONBOARDING.zh-CN.md)或[原生安装](NATIVE_INSTALL.md)。本页也保留早期固定工具模式的操作方式，两个模式不要混用。

## 身份、预算与账本

`scripts/prepare-model-guard.py` 在 POSIX 私有文件中生成不同的操作者与角色凭据。真实模型 key 留在操作者／Guard 一侧；角色 key 绑定 run、角色、模型别名和证据哈希，调用方自带 request ID 不改变绑定。SQLite 账本与完整配置哈希拒绝修改已有 run；轮换时建立新 run，并保留旧账。

早期串行模板限额为总共 9 次请求、每角色 3 次、并发 1、输入 300,000 token、输出 24,000 token、单次输出 6,000 token。**这不是当前原生团队默认预算**；原生准备器的默认值见原生安装指南和实际私有配置。所有这些数值都是部署限额，不是模型能力或费用承诺。

输入预留按完整请求序列化 UTF-8 字节数加 2,048 估算，不是已验证 tokenizer 上界，也不能保证最终账单上限。供应商返回 usage 后结算，超额停止 run；usage 仍可能与供应商账单口径不同。

同角色完全相同的规范化请求不会重复转发，重启后仍保留去重；它不是语义相似检测。预算和并发在分发前通过 SQLite 事务预留。服务不自动重试供应商请求，忙时拒绝，不使用内部队列。固定 `guard` 模式下，同工具／错误指纹两次结构化失败会停止 run。

关闭通过进程锁与原子账本变更和分发排序，但已经发出的调用不能撤回。超时、usage 缺失或持久化失败会保留预留并停止新请求；未知请求不会仅因超时释放额度。重启后默认未开启，有不确定预留时不能重新开启。

## 固定工具模式的历史操作顺序

在私有 Linux／WSL 环境执行，凭据不要写在命令参数、仓库或公开产物中。

1. 用 `scripts/prepare-model-guard.py --bundle benchmark/investigation/cases/case-001.json --run-id <new-id> --name-prefix <new-prefix> --model-env /root/.config/cyberguard/agentteams-llm.env` 生成新配置。路径按实际安装调整；脚本不覆盖旧文件，旧配置应私有归档。
2. 将 `services/model-guard/Dockerfile` 构建为 `cyberguard/model-guard:local`，启动 `compose.model-guard.yaml`。旧默认 env 位于 `/root/.config/cyberguard/model-guard.env`，本机端口 18110，Worker 经 Docker 网络访问。
3. 保持未开启状态，核查 Worker 实际工具、独立 provider、consumer allowlist、空队列及后台模型调用设置；处理可能绕过该路由的旧 Worker／Manager。
4. `python3 scripts/control-model-guard.py status` 核对 run 和用量。未开启的模型请求只记录工具名／定义哈希后拒绝，不转发；`GET /v1/models` 也在本地完成。
5. 预检后用 `python3 scripts/control-model-guard.py arm` 开启，按该历史配方逐角色运行任务；`close` 永久结束本轮，保留账本和证据。

控制脚本可加 `--output <new-file>` 保存快照。关闭后用 `python3 scripts/export-model-guard.py --output <new-directory>` 导出元数据、trace 和来源／导出哈希。在途未知用量可能之后结算，不要把早期快照当最终账单。卷内包含 `admission.sqlite`、请求记录和未开启时的工具声明，不应删除或重置来掩盖失败。

## 工具与传输范围

固定模式允许动态 Skill 及读取证据、读取报告、提交报告三个调查 MCP 函数，开启前核对实际工具声明。它会拒绝未允许的声明，以及供应商响应中不在本次声明内的工具调用。这不等于撤销 Worker 本来拥有的 shell、文件、网络或其他模型路径，相关权限由 AgentTeams／Higress 管理。

上游请求缓冲并使用 `stream=false`，结算后才合成 SSE 兼容响应，不是逐 token 流式输出。请求上限 1 MiB，响应上限 4 MiB。早期默认 socket I/O 超时 90 秒，不是总墙钟截止时间；持续缓慢返回可能更久。原生模板可配置不同超时。关闭 run 只阻止新请求，不取消在途调用。当前没有分布式故障切换或按用户隔离。

trace 对已知凭据及有限 JSON 转义形式做替换，不是通用秘密检测。存储视为敏感，发布前应扫描。证据哈希绑定账务元数据，本身不限制通用 MCP 能读取哪些材料；早期共享 MCP 实验不等于跨 run 安全沙箱。

## 验证与原生工具策略

`tests/test_model_admission.py` 覆盖不可变绑定、原子预算、独立进程、崩溃／未知预留与结算；`tests/test_model_guard.py` 用模拟传输验证大小限制、关闭竞争、去重、身份、工具约束与失败行为，不付费调用模型。

早期三 Worker 串行实跑验证实际 Worker→模型→MCP→网关集成，本身不证明自主规划或多 Agent 性能收益。当前原生 Task 的实跑证据另见[完整案件](FULL_CASE_VALIDATION.md)。

`tool_policy=runtime` 时，工具授权交给 AgentTeams；Guard 仍验证模型身份并预留请求／token 预算，但不重复工具白名单，也不因重复工具错误自动关闭 run。默认 `guard` 模式保留固定策略，以兼容旧部署。
