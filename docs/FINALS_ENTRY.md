# CyberGuard 决赛演示入口

**让 Agent 的调查有据可查，让处置结果经得起复核。**

从一起挖矿事件出发：第一轮已经成功停止进程，为什么仍然没有解决问题？CyberGuard 将调查、证据引用与独立复核交给原生 AgentTeams，并以审批和效果探针约束后续处置。

## 三分钟看懂

1. **看一次完整调查：** [014 原始材料](validation/full-case/014/materials.json) → [原生任务图](validation/full-case/014/workflow.json) → [最终报告](validation/full-case/014/skill-report.json)。重点找 R1 未达清除目标、R2 观察窗口和归因证据不足三项判断。
2. **看亮点如何落到实现：** [一页能力与证据表](PROVEN_CAPABILITIES.md)。013 / 014 在同一配置连续通过关键验收，耗时 5 分 7 秒 / 3 分 52 秒。
3. **看同一现场案件完成闭环：** [原生调查与动态提案](LIVE_RESPONSE_DEMO.md)，实时材料 → 原生调查 → 提案 → 审批 → 执行 → 复核失败 → 新一轮原生调查 → 再提案 → 再验证。677.60 秒、20 项检查通过。[打开同案证据页](validation/live-response/LIVE-HOST-a3f9b38ac1a349b9ab1b7617b1a1d959/review.html)。

## 自己使用

| 你想做什么 | 入口 |
| --- | --- |
| 从零部署完整调查服务 | [原生后端安装指南](NATIVE_INSTALL.md) |
| 启动控制台 | [快速开始](QUICKSTART.zh-CN.md) · [登录、HTTPS 与会话配置](OPERATIONS_DEPLOY.zh-CN.md) |
| 将已有 Agent 连接进来 | [Skill 安装与连接](EXTERNAL_AGENT_SKILL.md) |
| 配置真实调查后端 | [AgentTeams 原生任务服务](AGENTTEAMS_TASK_SERVICE.md) |
| 不调用模型，检查已发布证据 | [运行汇总](validation/full-case/summary.json) · [完整验证记录](FULL_CASE_VALIDATION.md) |
| 录制或现场展示 | [演示顺序与录制脚本](JUDGE_DEMO.md) |

本机控制台为 `http://127.0.0.1:18120`，调查入口 `/investigations`，Skill 连接入口 `/connect`。这些是安装后在本机访问的地址；远程部署使用配置好的 HTTPS 域名。

## 视频与版本

[新版演示视频](https://github.com/elsechord/CyberGuard/releases/download/v0.15.0/cyberguard-finals-20260920.mp4)：同一案件的两轮真实 Console 调查与现场响应原始记录，展示失败后重新调查和提案；屏幕标明已完成运行回看、实验环境与测试批准方式。

[已发布的 82 秒视频](https://github.com/elsechord/CyberGuard/releases/download/v0.14.1/cyberguard-demo-final.mp4)保留作早期服务流程介绍。旧片作为历史对照保留；最新主证据是上方同案原生调查与现场处置闭环，013 / 014 则提供独立的调查重复性记录。

下载源码时保留所用 Git 提交号：`git rev-parse HEAD`。提交材料中的源码包、PPT 截图和演示报告应对应同一冻结版本。运行证据是合成演练材料，报告、任务图与语义审阅分别保存，便于逐项核对。
