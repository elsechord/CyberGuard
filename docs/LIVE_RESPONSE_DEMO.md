# 现场处置演示：执行成功之后

这条演示把重点放在一个问题上：**进程已经结束，为什么事件还不能关闭？**

模型读取 Linux 实验环境的新鲜进程观测，生成受限处置提案。操作员先批准停止当前计算进程；执行器确实完成操作，但独立采样发现监督进程把它重新拉起。模型读取失败结果和新证据，再提出关闭持久化入口的方案。第二次批准、执行之后，复核同时检查异常计算进程消失、持久化文件移除，以及正常控制进程仍持续工作。

2026-09-20 实测：同一个 Linux 实验环境完成两轮 AgentTeams 原生调查、提案、真实审批接口、执行和独立采样，**20 项链路检查通过，全程 11 分 17.6 秒**。[原始运行记录](validation/live-response/LIVE-HOST-a3f9b38ac1a349b9ab1b7617b1a1d959/manifest.json) / [完整时间线](validation/live-response/LIVE-HOST-a3f9b38ac1a349b9ab1b7617b1a1d959/trace.json)。此次验收由测试程序批准，现场人工入口如下。

## 现场操作

在 Linux 或 WSL 中，安装项目的 Python 服务依赖。配置一个仅本机保存的 JSON 文件：

```json
{
  "upstream_endpoint": "https://your-provider.example/v1/chat/completions",
  "upstream_key": "YOUR_PRIVATE_KEY",
  "model": "YOUR_MODEL"
}
```

然后从仓库根目录运行：

```bash
python scripts/live-host-response.py \
  --planner-config /private/planner-config.json \
  --native-console-url http://127.0.0.1:18120 \
  --skill-key-file /private/cyberguard-skill-key \
  --output artifacts/live-host-response \
  --interactive
```

两次提案都会在终端展示动作、实时目标、风险、是否可逆和方案摘要。现场人员阅读后，分别输入屏幕上的 `approve ACT-...`。程序才会携带独立审批凭据调用审批 API，并发送执行请求。直接回车或输入其他内容会终止运行。

第一步的演示口播是：**“我们先按操作员要求，只停止当前异常进程，看独立复核是否允许事件关闭。”** 这是明确的初始处置范围，不是模型误判的包装。

自动验收使用 `--auto-approve` 替代 `--interactive`。这仍经过真实审批 API 和方案哈希校验，但批准人记录为测试程序，不能当作现场人工操作录像。

## Docker 运行

使用已经构建的 Console 镜像可复用其 Python 依赖。这里以 Linux 路径为例，配置文件只读挂载：

```bash
docker run --rm -it --user 0 --network host \
  -v "$PWD:/workspace" \
  -v /private/planner-config.json:/run/planner-config.json:ro \
  -v /private/cyberguard-skill-key:/run/skill-key:ro \
  -w /workspace --entrypoint python cyberguard/operations-console:0.15.0 \
  scripts/live-host-response.py \
  --planner-config /run/planner-config.json \
  --native-console-url http://127.0.0.1:18120 \
  --skill-key-file /run/skill-key \
  --output artifacts/live-host-response --interactive
```

无需 privileged、Docker socket 或宿主进程命名空间。操作对象都是本次实验创建的无害子进程，不运行真实挖矿程序。受限提案转换器每次最多两个模型请求，各限制 1500 输出 tokens；没有失败重试。原生调查的模型调用由 AgentTeams 预算单独管理。18120 是本机标准 Console 端口，本次隔离验收另用了 18136。

## 和 AgentTeams 调查的关系

`--investigation-report` 把已完成的 AgentTeams 调查报告送给规划器作为案件背景，记录原报告 SHA-256，并将该摘要绑定进处置提案的理由。进程和持久化目标始终从本次实时采集产生，不能拿历史报告里的 PID 执行。

默认模式的现场处置规划器是独立的受限模型调用；原生 AgentTeams 已负责前序调查报告。仅传历史报告时，这两个环境不是同一台受害服务器。演示时可以自然地说：**“前面是调查材料的研判，现在把同类复发问题放进可操作的 Linux 实验环境，验证授权和效果。”**

`scripts/live-host-response.py` 中的 `plan()` 将调查报告转换为 `{action,target,reason}`，保留实时目标白名单和操作员范围校验。原生模式先通过公开调查 API 等待 AgentTeams 结构化报告，再进入同一提案入口。审批凭据仍只留在操作员通道，不加入 Task。受限模型的提案转换调用不计为原生 Task。

## 可核验产物

每次运行目录包含：

- `manifest.json`：执行性质、批准方式、模型 usage 和逐项验收结果。
- `trace.json`：新鲜采集、模型提案、审批回执、执行回执和独立复核。
- `run-export.json`：同一个 run 的证据及审计完整性结果。
- `investigation-report.json`：作为背景的原始调查报告。
- `SHA256SUMS`：本次导出文件校验值。

公开实测保存在 [live-response](validation/live-response/)；其中 `approval_mode=automated_lab_harness` 明确表示自动验收批准。两轮动作的复核结果应依次为 `failed`、`verified`，未经批准的执行请求应两次均返回 409。

## 同一实时案件的原生调查模式

在上述命令中增加：

```bash
--native-console-url http://127.0.0.1:18120 \
--skill-key-file /private/cyberguard-skill-key \
--native-deadline 900
```

每一轮先把该实验的新鲜观测（第二轮包括前次真实失败复核）送入公开 Skill 调查 API，由 AgentTeams 原生任务完成调查和独立报告复核。收到结果后再采集一次现场状态，受限规划器读取原生报告和最新目标产生真实提案。两轮原生 job ID、请求、完整状态和报告分别写入 `round-N-native-*.json`，报告摘要绑定进同轮提案。原生失败或超时不会绕过调查继续执行；超时调用取消接口。

Docker 调用本机 Console 时可加入 `--network host` 并挂载 Skill key 为只读文件。该选项仅共享网络，不共享宿主 PID；无害实验进程仍位于容器进程命名空间。原生模型预算由 Console/AgentTeams 部署单独管理，本脚本的两个请求限制仅指提案转换器。

本次原生调度与调查使用 95 次请求、3,596,130 输入 tokens、84,430 输出 tokens；两次提案转换另使用 14,706 输入、932 输出 tokens。费用取决于所接模型服务的计价。当前原生编排上下文开销较大，演示视频可快进调查等待，注明真实耗时即可。

本次模型预算文件中的 `evidence_hash` 是预先保留的旧预算标签，不作为这次案件的材料绑定依据。两轮实时材料的 SHA、原生报告 SHA 与提案理由绑定记录，分别在 `round-N-native-job.json`、`manifest.json` 和 `trace.json` 中核验。
