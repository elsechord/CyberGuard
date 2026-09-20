# 原生临时 Agent 协作验收

日期：2026-09-20。环境为本机 AgentTeams v1.2.3 / QwenPaw，模型 deepseek-v4.1-flash。全部输入为合成材料。

## 实际结果

| 项目 | 结果与依据 |
| --- | --- |
| 数量可变 | 两份计划经原生 WorkerFlow 分别创建 1 和 2 个临时 Agent，实际读取 API profiles |
| 模型继承 | 子 Agent active_model 与父 Worker 一致，max_iters 生效，自动标题关闭 |
| 结束回收 | 原生 workflow_fail 结束测试，全部实例删除后返回 404，shared 记录保留 |
| 子 Agent 与同级双向通信 | A 实际调用 chat_with_agent 向 B 询问记录间隔，收到 5 分钟答复；原生 SSE 调用与成功返回以 call_id 配对 |
| 子 Agent 与父 Worker 双向通信 | A 向 default 求证是否支持成功入侵，收到不支持的答复；存在匹配的原生调用与成功返回 |
| 简单问题不扩张 | 父 Worker 直接回答，无工具调用，配置的 Agent 列表未增加；仅是一个样本 |
| 费用 | 6 次模型请求，80,288 输入 token、1,131 输出 token；无预算拒绝；结束时无在途调用，验证预算已关闭 |

通信运行 ID：`cg-comm-a7cee3ad35`。外部测试程序启动两个临时 Agent，并向 A 发出任务；A 后续对 B 和父 Worker 的工具调用由实际模型产生，没有用程序冒充 A。它证明通信能力，**不单独证明完整 Project 已自主选择最优人数**。本次 6 次调用与此前 89 次调试工作量不同，不能直接比较为性能提升。

## 修复的实际问题

新临时 Agent 不自动继承父 Agent 专属模型和运行参数，已改为显式配置并回读。刚创建即回收时原生可能返回 starting 状态的 HTTP 409；helper 对此进行 1、2、4、8 秒有界重试，仍失败则保留 partial_failed。

原生通信 SSE 使用 plugin_call / plugin_call_output；初版检测器不能识别，已离线修正并核对保留事件，没有重复模型测试。

## 复现

- `deploy/investigation-service/install-collaboration.py`：安装到三个 Worker，保留原模型、工具与通信配置。
- `deploy/investigation-service/validate-collaboration.py`：无模型调用的原生生命周期测试。
- `deploy/investigation-service/validate-collaboration-messages.py`：有界真实通信测试；支持 analyze-only 离线分析。

本轮回归：原生适配 9、协作 helper 14、协作展示 4、任务/API 15、控制台 51，共 93 项测试通过。本机主 Console 已更新，协作 Skill/helper 已重新安装到三个 Worker，并确认原有配置保留。

公开证据：[原生生命周期](validation/adaptive-collaboration/native-lifecycle.json)、[带调用与返回配对的通信记录](validation/adaptive-collaboration/native-communication-summary.json)、[模型用量账本](validation/adaptive-collaboration/model-budget.json)。完整 native-communication.json 保留在本地 `output/adaptive-collaboration/` 排障；公开材料不包含长篇模型过程。

## 当前边界

团队 Docker Worker 仍为一个 Leader 和两个 Worker。动态数量发生在 Worker 内部的临时专家层，默认单次最多 3 个、深度 1；不是 Docker 自动扩容或全平台并发配额。临时 Agent 使用父 Worker 的计费身份。普通通信摘要由 Agent 记录，不能仅凭填写 event_id 就当作已核验通信。

完整 Project 的自主拆分、长期稳定性、取消时在途工作流收尾及同预算质量/效率比较，仍需真实案件评测。证据引用校验、独立团队复核和处置审批保留。
