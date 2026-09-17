# Evidence → investigation → review

本地调查链已接通：导入不可变证据包，创建绑定运行，以只读工具获取证据，生成带引用的报告，用单独凭据提交并校验，再导出工具回执及报告。默认运行固定规则基线；没有模型凭据时，单 Agent、多 Agent 和 AgentTeams 均保持 `not_run`。

## Docker 复现

```sh
docker compose -f compose.investigation.yaml up --build --abort-on-container-exit --exit-code-from investigation
docker compose -f compose.investigation.yaml cp investigation:/artifacts/. artifacts/investigation/
```

流程覆盖三份明确标记为 exercise 的材料，以及一次真实采集当前 Linux 容器 `/proc` 的证据包。**真实容器采集并不等于真实入侵事件**。没有恶意程序、处置动作或外部网络请求。生成 evidence.json、report.json、report.md、run-export.json、manifest、源码文件哈希与 SHA256SUMS。

实验镜像不复制 `benchmark/investigation/evaluator-only` 或案例生成器。标准答案仅用于独立评测；实际模型通过只读 MCP 获取指定运行的证据包，不应挂载完整代码仓库或评测目录。

## 自己的证据材料

Linux 只读采集、范围、权限限制及脱敏说明见 [证据包文档](EVIDENCE_BUNDLES.md)。配置和日志均需明确指定范围；默认不读取进程环境或命令行。离线分析入口：

```sh
python scripts/collect-linux-evidence.py --output artifacts/my-evidence.json
python scripts/investigate-evidence.py artifacts/my-evidence.json --output artifacts/my-investigation
```

目前基线关联 CPU 观察、程序路径、持久化配置和授权清单，产出待复核线索。不能因为 CPU 高、程序位于临时目录，就认定是矿工或某攻击组织。配置存在也不等于调度器已启用。缺失信息进入 unknowns 和 next_collection。

## 调查 API

|接口|凭据|行为|
|---|---|---|
|`POST /investigations/bundles`|`CYBERGUARD_INVESTIGATION_INGEST_TOKEN`|导入最多 8 MiB、通过完整性验证的证据包；同 ID 不可换内容|
|`POST /investigations/runs`|同上，仅操作员|固定 run_id、bundle hash、mode、工具范围和预算|
|`GET /investigations/runs/{run_id}/evidence`|`CYBERGUARD_API_TOKEN`|读证据，记录运行绑定的工具回执|
|`POST /investigations/runs/{run_id}/reports`|`CYBERGUARD_REPORT_TOKEN`|校验直接传入的报告 JSON，记录提交回执；不执行任何响应动作|
|`GET /investigations/runs/{run_id}/reports`|只读 token|导出运行、报告及回执；检查跨运行、内容与序号绑定|

两种写入 token 必须至少 32 字符，并与其他调查角色 token 不同。默认没有配置写入 token 时相应接口关闭。`compose.yaml` 已传入这些可选变量；不要把导入凭据或人工审批密钥提供给 Worker。

本机操作员可使用 `scripts/import-investigation-run.py`，从 POSIX 0600 配置文件读取导入 token，并生成不含凭据的准备回执：

```sh
python scripts/import-investigation-run.py --bundle artifacts/my-evidence.json \
  --run-id investigation-001 --mode multi_agent \
  --env-file /root/.config/cyberguard/services.env --output artifacts/run-prepared.json
```

此命令只准备运行，不会触发模型任务。默认连接 `http://127.0.0.1:18100`，拒绝重定向和非本机目标，避免意外向其他地址发送操作员凭据。

创建运行请求示例：

```json
{
  "run_id": "investigation-001",
  "bundle_id": "REPLACE_WITH_IMPORTED_BUNDLE_ID",
  "mode": "fixed_workflow",
  "budget": {"max_input_tokens": 20000, "max_output_tokens": 8000, "max_tool_calls": 16}
}
```

`mode` 可为 fixed_workflow、single_agent、multi_agent；三者工具/权限相同。网关强制执行读取证据和提交报告合计的调用配额；同内容重复提交幂等，不重复扣额。输入/输出 token 限额是运行契约，实际模型 runtime 还需强制执行并提供 usage，不能仅凭配置声称未超预算。

API 接受报告只证明 schema、证据引用和运行绑定有效，不证明内容正确、模型参与或 AgentTeams 执行。导入者自带 hash 也不证明来源真实。数据库在本地受信任存储边界内；当前不是企业多租户服务。为了盲测，各模式应使用隔离的网关数据目录和凭据，避免通过共享只读 token 读取其他运行的报告。

## 真实 AgentTeams 和评测

[AgentTeams 调查接入](AGENTTEAMS_INVESTIGATION.md)提供三角色、只读/报告 MCP、任务包生成器和原始运行证据结构校验。先保存实际 Task/Worker/Skill/工具/模型 usage，再判断是否完成真实协作；结构一致不等于来源认证。

[调查评测说明](INVESTIGATION_EVALUATION.md)提供统一证据/工具/权限/预算协议、三个演练检查及模型结果导入。当前规则评测用于检查拒绝误判、保留未知项和正确引用等行为，不能把小样本规则检查通过率称为安全调查准确率或多 Agent 优势。

`scripts/run-investigation-model.py` 可通过显式指定的 HTTPS 模型端点运行真实单 Agent 工具循环。该入口仅允许 exercise 证据包；模型只能读取该包、提交报告，不能读取本地文件、评测答案或调用处置工具。原始请求、响应、工具失败和 provider usage 会保存到新建输出目录。凭据通过环境或私有配置文件读取；不要在命令行参数中传入密钥。运行器采用保守的输入大小预检，可能在实际 token 尚未耗尽时停止纠错；失败和未知费用必须保留，不能用规则报告替换。该运行器本身不是 AgentTeams。
