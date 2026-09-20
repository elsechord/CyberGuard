# 调查服务本地验收记录

验证日期：2026-09-20。输入为明确标注的合成登录记录，包含一段要求无证据确认攻击者归属的恶意文本。没有提交真实客户材料，也没有执行处置动作。

## 旧串行后端实际执行

- Console HTTP API 接收任务 `INV-56e68f7cac424c9a9c8c4d738658ab94`，重复提交返回相同任务 ID。
- 三个不同的 AgentTeams Worker 依次完成 investigator、planner、verifier 阶段；保存真实 Matrix 请求/响应事件与 Worker 身份。
- 最终报告引用原始材料，并明确拒绝材料中的指令，保留登录是否获授权等未知项。该单一案例不构成通用提示注入防御或专业调查准确率的评测。
- Skill v0.2.0 的 `check --investigations`、`submit`（重放同一幂等键）、`status`、`result` 均对这个真实 API 任务通过验证；没有产生额外模型调用。
- 浏览器验证了任务提交、原文展开、取消、实际完成报告展示，以及点击报告引用定位并展开原文。

成功的一轮使用 3 次真实模型调用、20,590 输入 token、2,608 输出 token。前两轮分别暴露了思考消息中的格式示例被误解析、2,000 token 输出上限截断报告的问题；其失败/取消任务及账本保留。最终每请求上限调整为 3,500，所有轮次合计 7 次调用、41,080 输入 token、6,722 输出 token，未超过原先设置的 9 次/150,000 输入/12,000 输出总限额。

## 自动检查

| 检查文件 | 通过数量 |
| --- | ---: |
| `tests/test_operations_console.py` | 51 |
| `tests/test_external_agent_skill.py` | 6 |
| `tests/test_investigation_intake.py` | 6 |
| `tests/test_investigation_jobs.py` | 14 |
| `tests/test_agentteams_bridge.py` | 11 |
| 合计 | 88 |

包含并发幂等、持久化恢复、权限隔离、分页、取消竞态、租约过期、材料篡改、报告引用校验、预算等待与 UI 的 CSRF/转义。单元测试中的后台替身与上述真实 Worker 运行分别记载。Python 编译、前端脚本语法检查和 Docker 构建通过。

## 当前本地状态

主控制台 `http://127.0.0.1:18120` 已重建，沿用原用户与数据卷；调查入口为 `/investigations`，Skill 连接入口为 `/connect`。Matrix 已配置。验证用模型守卫已关闭并排空，新任务会停留在“等待模型预算”；后续真实调用需配置新预算或常驻生产后端。隔离验证控制台 18135 已停止，其数据卷与报告仍保留。

公开可审阅的本地合成验证产物在仓库同级 `output/console-agentteams-validation-001/attempt3/`，包括 `job-result.json`、`report.json`、三个角色的 Matrix 记录、`guard-final.json` 和 `skill-validation.json`。密钥只在私有配置目录，未写入仓库。

本次证明真实 Worker 编排与任务服务链路，不证明 AgentTeams 原生 Task 调度完成，也未实现跨租户运行环境隔离、原生 PDF/OCR 或所有厂商连接器。财务与法律当前支持文本材料接入和报告草稿，未验证专业结论质量。运行设置见 [AgentTeams 任务服务](AGENTTEAMS_TASK_SERVICE.md) 和 [本地验证部署说明](../deploy/investigation-service/README.md)。


## 原生 Project/Task 接入（2026-09-20）

AgentTeams Controller/QwenPaw 已升级为官方 v1.2.3，旧 Controller 数据备份保留。新后端默认为 `native`；旧串行任务继续使用原协议。

- Skill 实际提交：`INV-f49a7162f7c14a548763c79a2d1d9bdf`。
- 原生 Project：`cg-inv-f49a7162f7c14a548763c79a2d1d9bdf`。
- Leader 自行规划两个原生 Task（ID 后缀 `-01` / `-02`），分别委派调查与独立复核给不同 Worker。
- 两项 Task 均经原生 `accept_task_result` 验收，节点状态为 completed。Worker 提交的 `report.json` 从 Controller Task artifact API 读取，逐字引用校验通过。
- 在原生节点全已验收后，Console 调用官方 Project complete API 收尾，并重新查询到 Project completed。没有手改 Task/Project meta.json。
- 实际 Skill `result` 成功取回报告；浏览器展示原生负责人、任务状态、调查结果和原文引用。
- 本次针对性测试：原生适配 7、持久化任务/API 15、模型网关 27、控制台回归 51，共 100 项通过。

### 人工介入和效率限制

这不是无人干预成功率证明。初始模型预算不足，保留原账本后使用两次有上限的续跑预算；人工通知 Leader 恢复同一个 Project。复核产物最初不符合要求，Leader 要求返工；人工补充了通知方式，并拒绝与交付无关的临时文件清理请求。最终 Project 收尾已改为代码调用官方 API，不再依赖额外模型推理。

本次模型存在重复查文件、长篇自我推敲、错误工具参数和不准确的提及触发等效率问题。提示词已增加原样传递报告格式、使用完整成员标识及委派后等待原生事件的要求，但改后尚未完成一次全新、无人协助运行。

三份独立保留的预算账本合计：89 次模型请求，已知输入 3,096,246 token，输出 67,691 token。这是整次调试总量，不是正常单任务成本基准。

验证预算已关闭且无在途请求，后台与数据仍保留；新调查需要运营者配置/开启正常服务预算。主 Console 位于 `http://127.0.0.1:18120`，验证页面位于 localhost:18136。完整本地证据在上级工作区 `output/native-task-service/`：job-result.json、skill-report.json 和三份预算记录。

当前消息内联传输有 60 KiB 上限；大型材料包仍需后续接入原生共享产物传输。模型工具权限交给 AgentTeams，Model Guard 的 runtime 模式保留身份与预算控制；既有处置审批不变。


## 完整案件重复运行

后续完整挖矿事件的诊断、修复和独立运行结果见 [完整案件验证](FULL_CASE_VALIDATION.md)。其中明确区分合成事件回放与真实处置执行。
