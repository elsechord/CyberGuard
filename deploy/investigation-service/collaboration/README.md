# Native WorkerFlow collaboration helper

Run this CLI **inside the owning QwenPaw Worker**, using its Python runtime and
existing Matrix/runtime environment. It loads the installed AgentTeams v1.2.3
WorkerFlow module. It neither invokes a model nor schedules child conversations.
The owning Worker sends native `submitInstructions` using QwenPaw communication
tools and calls `update` after receiving actual results.

The installed module path defaults to the path verified in the v1.2.3 Worker image:

```
/opt/agentteams/qwenpaw-builtin/plugins/workerflow/workerflow/mcp/server.py
```

Override with `--native-module` or `CYBERGUARD_WORKERFLOW_MODULE` for a different
installation. The CLI fails if that file is absent; it does not emulate WorkerFlow.

Example plan (store privately in the Worker workspace, not as a public artifact):

```json
{
  "job_id": "INV-example",
  "task_id": "task-example",
  "parent_worker": "investigator",
  "parent_agent_id": "default",
  "depth": 1,
  "run_id": "cg-example-investigation",
  "room_id": "!actual-task-room:matrix.example",
  "reason": "Two independent sources need correlation",
  "materials": [
    {"material_id": "MAT-a", "content": "original source text"},
    {"material_id": "MAT-b", "content": "other original source text"}
  ],
  "nodes": [
    {"id": "host", "subagent": "source-reader", "role": "Host evidence",
     "question": "What does the host record establish?", "material_ids": ["MAT-a"]},
    {"id": "network", "subagent": "source-reader", "role": "Network evidence",
     "question": "What does the network record establish?", "material_ids": ["MAT-b"]}
  ]
}
```

Install referenced templates under the default workspace `subagents/<name>/`.
`--task-dir` must name an existing TeamHarness task artifact directory; this
helper does not create a Task or change its acceptance state.

```bash
python native_collaboration.py start --plan plan.json --task-dir /actual/task/directory
python native_collaboration.py update --plan plan.json --task-dir /actual/task/directory --data update.json
python native_collaboration.py record-message --plan plan.json --task-dir /actual/task/directory --data message.json
python native_collaboration.py finish --plan plan.json --task-dir /actual/task/directory
```

An update is native WorkerFlow data, for example
`{"steps":[{"id":"host","status":"done","summary":"Source establishes X"}]}`.
Inspect every native response for newly ready instructions.
The returned submit/waiting/ready instructions also carry `parent_id: "default"`
and `peer_agent_ids`. The coordinator should include these names when forwarding
the submit prompt so children can ask their parent or peers targeted questions.
These routing hints do not modify the native workflow file.

A message is an
optional short journal entry with `from`, `to`, `kind`, `question`, `answer`,
`changed_conclusion`, `event_id`, and/or `task_id`. Entries are always marked
`agent_recorded`: an entered event ID is not a verified transport receipt.

The helper inherits `active_model` explicitly from `/api/agents/default`, configures
each new child's `running.max_iters` (default 10), disables automatic title calls,
and reads the updated configuration back before returning submit instructions.
If child configuration fails it requests native failure cleanup.

Defaults allow at most three temporary agents **per run**, at the first level
below the default Worker. `--max-agents` / `CYBERGUARD_MAX_SUBAGENTS` adjusts the
per-run limit. This is an execution convention, not a global concurrent-agent
quota or a sandbox against other native tools; runtime/model budget controls
remain responsible for aggregate resource use. Temporary-role instructions should
direct children to report to their parent instead of recursively spawning.

`finish` and `fail` use native cleanup, delete temporary workspaces, and retain the
shared run evidence. If native deletion returns HTTP 409 because a child is still
starting, these commands retry native cleanup after 1, 2, 4, and 8 seconds, then
expose any remaining cleanup failures. They do not involve a model or retry forever.
Project cancellation stops subsequent native task scheduling;
the owning Worker must finish or fail any in-flight internal workflow to clean it
up. There is no background janitor in this helper.

The native `workflow.json` remains authoritative. `collaboration.json` is a compact
projection for the Console: job/task identity, parent Worker, run rationale, real
node statuses, referenced material IDs, short summaries, recorded messages, and
cleanup outcomes. Original input, submit prompts, credentials, model configuration,
and absolute workspaces are omitted. Start returns native submit prompts to its
coordinator, so do not publish its raw stdout as the Console artifact.

`tests/test_native_collaboration.py` uses native-return fixtures and performs no
model calls. Passing it is not proof of live peer communication or autonomous
multi-agent completion.
# Original case delivery

`install-collaboration.py` also installs `case_packet.py` for all participating
Workers, including runs that use no temporary specialists. The Console uploads
the original material bytes and report contract as a Matrix media packet. Use
the packet URI and job ID supplied in the current task specification:

```sh
python /opt/cyberguard-collaboration/case_packet.py fetch \
  --uri mxc://SERVER/MEDIA_ID --job INV-CASE --directory shared/tasks/TASK_ID
python /opt/cyberguard-collaboration/case_packet.py check \
  --case shared/tasks/TASK_ID/case.json --report shared/tasks/TASK_ID/report.json
```

Fetch uses the Worker's existing Matrix identity and verifies material hashes.
Check validates output structure and exact citations; it does not judge the
truth of a conclusion. Use the file-writing tool to write report/script content,
then execute saved scripts by path. Keep evidence text out of shell heredocs.
# v1.2.3 原生委派地址兼容

`install-collaboration.py` 也会安装 `native_identity.py`，修正 v1.2.3 将 Worker
短名直接发送为 Matrix mention 的问题。补丁在原生 delegate_task 的成员检查、
保存和投递之前，使用真实 Team 成员配置解析地址，不改已有任务状态。
安装后重启对应 Worker，使内置插件同步并重新加载；不要在运行案件期间重启。
Worker 容器被重新创建后必须重新安装这些容器内资产。升级上游时应检查是否已
修复并移除本补丁；安装器在源码锚点不匹配时会拒绝盲目应用。

本地嵌入式部署另有启动路由兼容修正：仅将错误的
`http://agentteams-controller:8080/cg-guard/...` 数据请求地址映射到实际数据面
`http://aigw-local.agentteams.io:8080/cg-guard/...`，保留角色路由、认证和预算检查。
其它主机、端口、路径及外部模型地址不变。该修正应用在 Worker 启动配置加载处，
使普通容器重启后仍使用正确网关；换部署拓扑或升级上游时必须复核此映射。
