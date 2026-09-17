# AgentTeams on the local Docker Desktop engine

The official AgentTeams v1.2.2 release is pinned to commit
`849182af8e017168a5a200a87b1062142caf462d`. Its embedded image includes the
Controller, embedded Kubernetes API, Tuwunel Matrix, MinIO, Higress, and Element.
Manager and Workers are separate containers created by the Controller.

Official sources: [release](https://github.com/agentscope-ai/AgentTeams/releases/tag/v1.2.2),
[installer](https://github.com/agentscope-ai/AgentTeams/blob/849182af8e017168a5a200a87b1062142caf462d/install/agentteams-install.sh),
[Docker backend](https://github.com/agentscope-ai/AgentTeams/blob/849182af8e017168a5a200a87b1062142caf462d/agentteams-controller/internal/backend/docker.go).
The downloaded installer SHA256 was
`8ef28c5bf239a0af2d6b57b946ecee977bf39e6c874cd786b85c7bd094668f9d`.
We inspected it, but did not run its cleanup/upgrade or credential-printing steps.
Reference source caches are in ignored `tmp/agentteams-local-source`.

## Local credentials and startup

Run with WSL Ubuntu-26.04 as root; Docker uses the existing Docker Desktop engine.
No global WSL/Docker configuration change or Docker reset is needed.

```bash
cd /mnt/d/Projects/CyberGuard/research-source
python3 deploy/agentteams-local/prepare-local.py
python3 deploy/agentteams-local/ensure-private-network.py
bash deploy/agentteams-local/build-controller.sh
docker compose -f compose.agentteams-local.yaml \
  -f deploy/agentteams-local/localhost.override.yaml up -d
```

The preparation script creates `/root/.config/cyberguard/agentteams-local.env`
with mode 0600 and preserves it on reruns. It contains randomly generated local
Matrix/MinIO/admin credentials. The base configuration disables Manager and uses
no model key. To enable the user-configured provider, keep its configuration in
`/root/.config/cyberguard/agentteams-llm.env` (0600), then add
`-f deploy/agentteams-local/model.override.yaml` to the Compose command.
Required model variables: `AGENTTEAMS_LLM_API_KEY`, `AGENTTEAMS_OPENAI_BASE_URL`,
`AGENTTEAMS_DEFAULT_MODEL`. The release's provider selector is `openai-compat`.
Never copy credentials into Worker prompts, task packages, or repository files.

Host endpoints bind only localhost: gateway/Matrix `18080`, Higress console
`18001`, Element `18088`, and Manager console `18888`. Dedicated volumes are
`cyberguard-agentteams-local-data`, `cyberguard-agentteams-local-workspace`, and
`cyberguard-agentteams-local-share`. No repository, evaluator answers, host user
directory, or unrelated credentials are mounted into Workers. The Controller
has Docker socket access to manage task containers; this is a local trusted
control plane, not a hostile multi-tenant service.

## Required upstream localhost patch

This is **not an unmodified upstream deployment**. In v1.2.2, Worker environment
creation unconditionally sets `AGENTTEAMS_CONSOLE_PORT=8088`; the Docker backend
publishes its random host port without `HostIp`. CoPaw and QwenPaw both exhibited
`0.0.0.0`/IPv6 publishing. Setting the task bridge's default bind to localhost did
not fix that explicit API request on this Docker Desktop engine.

`controller-localhost.patch` changes one automatic console binding to
`HostIP: "127.0.0.1"`. The pinned-source build runs a regression test and replaces
only `/usr/local/bin/agentteams-controller` in the official embedded image.
The image is named `cyberguard/agentteams-embedded:v1.2.2-localhost` and labeled
with the baseline revision and patch purpose. It is locally built, not published.
The patch does not alter arbitrary explicit `req.Ports` mappings; review any
future exposed ports separately.

Existing Worker containers retain their HostConfig across restart. Put these
task Workers to sleep with `agt worker sleep --name NAME`, verify they stopped,
remove only those stopped task containers, then wake them after the patched
Controller is active. Preserve credentials, Matrix state, Skills, and named
volumes. Verify both Docker PortBindings and actual localhost response before
starting any task. Do not rely solely on a Compose/network declaration.

`ensure-private-network.py --migrate-task-network` handles an existing dedicated
bridge only after checking every attached container against this task's explicit
allowlist. It briefly stops and reconnects the task containers, preserving aliases
and volumes; it refuses unrelated containers. No `prune` or global network rule
is used. The bridge default is defense in depth, not a replacement for the patch.

## Investigation MCP

The gateway must be on `agentteams-net` with alias
`security-tool-gateway.agentteams.local`; Higress rejects the short hostname as a
DNS service source. `register-investigation-mcp.py` reads only the read/report
tokens from `/root/.config/cyberguard/services.env`, sends them over stdin into
the Controller, and registers two narrow MCP servers via the actual Higress
Console API. No ingest or executor/approval credential is registered.

The report MCP supplies object/array item schemas. Inspect the actual `tools/list`
response to verify `findings[].limitations` and evidence references are string
arrays. A successful MCP registration does not prove a tool call or model run.

QwenPaw additionally applies its own Driver policy. In this installation the
initial investigation MCP policy was `ask`; a Matrix tool-call announcement
waited for approval and never reached the gateway. The narrow native API setup is:

```bash
python3 deploy/agentteams-local/configure-investigation-policy.py \
  --out /path/to/new-policy-audit.json
```

The script first persists all previous policies, then updates only the two
investigation MCP drivers. The policy defaults to deny and allows the three
named investigation tools only for Matrix sources. It reads back the policy and
uses the installed native policy evaluator to check the intended allow/deny
cases. **This does not restrict every built-in runtime tool.** The actual third
attempt included a built-in `execute_shell_command` listing its own shared task
directory. We did not enable that permission; it was available in the upstream
runtime. Do not describe this deployment as a runtime-wide read/report sandbox.
Cross-session calls still encountered `driver_policy_denied` despite these
deterministic checks, so policy propagation/context remains an unresolved issue.

## Evidence and boundaries

Record native Worker/Team configuration, Matrix events, Skill load evidence,
MCP tool receipts, report validation, actual provider usage, and image identities.
Run only exercise evidence through the external model provider in this session.
Do not send the host's `/proc`, network, logs, or secrets to the provider.
Manager startup and connectivity probes are setup overhead and must be reported
separately from task usage. Prompt budgets are not token enforcement. The current
AgentTeams run is an integration validation, not a fair fixed/single/multi-agent
comparison; `read_investigation_reports` is available and unmetered here.

## Observed local attempts on 2026-09-17

The local Controller, Matrix, Higress, MinIO and Manager were deployed, and three
QwenPaw Workers became ready on localhost-only console ports. The user-authorized
model was `deepseek-v4.1-flash` through an OpenAI-compatible endpoint. These are
deployment observations, not a successful investigation claim.

| Run | Observed Worker input/output tokens | Result |
| --- | --- | --- |
| `AT-INV-20260917-001` | 34,613 / 553 | Over the 20,000 input budget; native MCP approval pending; no gateway tool receipt. |
| `AT-INV-20260917-002` | 18,351 / 169 | Stopped at the 300-second observation limit; no gateway tool receipt. |
| `AT-INV-20260917-003` | 554,327 / 15,688 | Over the 150,000 input budget; one genuine gateway evidence-read receipt, no report submission. |

The third window had 23 completed native Worker model calls: planner 17,
investigator 2, verifier 4. Its native history shows Skill loads, a created task
room, repeated invitation-array schema errors and policy denials. The other two
Workers were activated but did not independently read the evidence or finish
their investigation roles. A room named Task is not proof of a completed native
Task. Therefore the strict run validator must not label this run complete.

The third attempt was stopped after 62.6 seconds. The external 15-second monitor
saw input usage jump from 80,441 to 410,943, and in-flight calls raised the final
count further while Workers stopped. This proves that the external monitor is
not a hard aggregate budget limit. Initial empty/missing usage files were marked
as assumed zero; the counters cover the observation window, not independently
attested per-run billing. Provider connectivity probes and Manager overhead are
separate and not covered by these three Worker sums. No fair mode ranking follows.

An operator-only `DIAG-INV-20260917-001` direct MCP call succeeded separately;
its receipt must never be merged into the model runs. Original Worker snapshots
are private under `/root/.config/cyberguard/attempt003/`; the repository-adjacent
`output/agentteams-local-20260917/native-history-003/` contains selected native
SQLite rows, original source hashes, and diagnostic excerpts. Checksums provide
integrity, not third-party attestation. No report or tool result was filled in by
the operator to make a failed run appear successful.

## Stopped state and safe next launch

All three Workers are intentionally `Sleeping`; the infrastructure remains up.
Do not run `wake` or reapply Workers just to view the demo: existing Matrix
rooms/sync positions and persisted conversations can trigger unfinished work.
The stopped `*-attempt002` containers were retained for forensic inspection.
A fresh container restored from MinIO was needed after the previous container
failed `mirror_all` on restart; this is an upstream runtime limitation observed
locally, not a resolved general restart guarantee.

Before another paid attempt, implement per-call admission/cancellation at the
actual model boundary with one shared run budget and persist task-to-call IDs.
Use a new run and an isolated new Team/Worker identity or the documented native
task cancellation API after auditing all pending tasks; merely changing the
prompt's run ID or recreating a container does not clear persistent queues.
Archive old Worker/Matrix state instead of deleting it. Validate native policy
in the actual task-room context and invitation schemas without a model first.
Only then launch a bounded new attempt; do not auto-resume any of these runs.
