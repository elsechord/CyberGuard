# Local AgentTeams task service

## Current native backend (v1.2.3)

See [native deployment and configuration](../../docs/AGENTTEAMS_TASK_SERVICE.md).
`controller-native.Dockerfile` and `native-controller.override.yaml` upgrade the
controller and QwenPaw runtime. `prepare-native-team.py` prepares the team and
budget route; `configure-native-team.py` configures ready Workers and the Console.
Use [the clean-host installation sequence](../../docs/NATIVE_INSTALL.md) for a new deployment. Preparation and configuration accept explicit plan/private/model paths and do not depend on a previous validation instance. Historical validation runners below retain their local fixture assumptions.

Native mode keeps TeamHarness and WorkerFlow enabled. Tool authorization belongs
to AgentTeams; the optional guard uses `tool_policy=runtime` for identity and cost.
`validate-native.py` submits a synthetic case through the actual Skill and saves
native workflow snapshots and the final artifact. Its 900-second bound is only a
test harness timeout; the production adapter has no per-role stage deadline.

## Historical serial validation (v1.2.2)


This directory provisions one bounded local validation, not an always-funded
investigation service. Production operators must supply ready dedicated Worker
rooms and an open, appropriately budgeted model route. A configured Matrix
connection alone does not establish model availability.

Prerequisites: WSL Ubuntu-26.04/root, Docker Desktop, the pinned AgentTeams
v1.2.2 localhost-patched controller image, preserved native infrastructure,
and private 0600 `/root/.config/cyberguard/agentteams-local.env` and
`agentteams-llm.env`. No secrets should be printed or copied to the repository.
Before restoring preserved infrastructure, inspect desired Worker/Manager states
offline and ensure they are Sleeping; do not start the model override that
enables the old Manager. This session verified those states before running:

```sh
cd /mnt/d/Projects/CyberGuard/research-source
docker compose -f compose.agentteams-local.yaml \
  -f deploy/agentteams-local/localhost.override.yaml up -d controller
python3 deploy/investigation-service/prepare-local-validation.py
python3 deploy/agentteams-local/register-guarded-routes.py \
  --plan ../output/console-agentteams-validation-001 \
  --guard-env /root/.config/cyberguard/console-validation-001/model-guard.env
python3 deploy/agentteams-local/apply-guarded-team.py \
  --plan ../output/console-agentteams-validation-001 \
  --out ../output/console-agentteams-validation-001/deployment.json
```

The preparation script deliberately refuses existing paths; these exact paths
have already been consumed in this session. For another deployment, review and
change RUN/PREFIX/private/output names, allocate a separate guard ledger, and
preserve previous usage. Never delete the ledger, rotate old run credentials, or
rearm a closed run as a way to reset its budget.

Fresh Worker startup hit the pinned upstream readiness bug. The existing
`deploy/agentteams-local/qwenpaw.Dockerfile` was built as
`cyberguard-qwenpaw:readiness-local` after its seven tests passed. Only the three
fresh Worker CRs received `spec.image` with that value. Original failed containers
were kept with `-startup-failed` suffix; no old Worker was resumed. Wake those
fresh Workers with `agt worker wake --name cg-console001-ROLE` only while their
guard is disarmed, then run:

```sh
python3 deploy/investigation-service/configure-local-validation.py
python3 deploy/agentteams-local/audit-guarded-routing.py \
  --plan ../output/console-agentteams-validation-001 --out NEW_ROUTING_AUDIT.json
python3 deploy/agentteams-local/probe-guarded-schema.py \
  --plan ../output/console-agentteams-validation-001 --out NEW_SCHEMA_PROBE.json
```

Inspect guard declarations before arming. These Workers have all native built-in
and MCP tools disabled, retry/background generation disabled, and fixed role
model routes. The dynamic Skill/memory tools have a separate guard allowlist.
Readiness must be revalidated after every reconstruction because upstream
startup can restore plugin defaults.

The configuration helper creates a private persistent Matrix bearer in
`/root/.config/cyberguard/console-validation-001/console-backend.env`. Use this as a
Compose configuration input, while preserving literal credential values; attach the console to existing
`agentteams-net`. Do not simply add a service-level `env_file` to the repository
Compose file: its explicit `environment` keys would override that file, even
when empty. Supply the corresponding interpolation values or a private
`environment` override instead (escape literal `$` as `$$` in Compose values).
The file has the internal Matrix URL, virtual Host, fixed
Worker rooms/senders, and token. It contains no provider credential. Do not paste
it into documentation or browser setup. `roles.json` under the output plan is a
non-secret mapping. Rotate the bearer only between jobs; in-flight token changes
fail closed to prevent duplicate Matrix dispatch.

An isolated console was built from the current source and run on localhost
18135 with volume `cyberguard-console-validation-001`. Its scoped API key lives
only in the private validation directory and console volume. The actual HTTP
runner `validate-http.py` arms the guard, submits one synthetic exercise,
checks idempotent replay, polls/export results, and closes the guard in `finally`.
It does not synthesize Worker responses. The first attempt exposed an adapter
parser issue and remains a failed terminal job. The second attempt used a fresh
guard ledger with the first attempt's consumption subtracted from the original
aggregate ceilings; no failed job or original ledger was rewritten.

The guard is closed after validation. Pointing the normal localhost18120 console
at these same rooms does not automatically authorize future inference. Before
accepting a new live job, provide a fresh reviewed model budget and ready routes,
or configure an independently managed production AgentTeams backend. Model
secrets and guard administration must remain outside the browser/API-key scope.
Validation artifacts under `output/console-agentteams-validation-001` distinguish
failed attempts, actual native messages, validated reports, and model usage.

For the normal console, set `CYBERGUARD_INVESTIGATION_REQUIRE_GUARD_ARMED=true`
and configure `CYBERGUARD_GUARD_URL` plus the private `CYBERGUARD_GUARD_ADMIN_TOKEN`
for the matching guard. Undispatched jobs then wait for an available armed budget;
jobs already dispatched continue collecting their existing responses. This
pre-dispatch check supplements the guard's actual admission enforcement.
The latest validation config is privately stored at
`/root/.config/cyberguard/console-validation-001/attempt3/model-guard-config.json`.
Its route is `http://console-model-guard.agentteams.local:8080` on `agentteams-net`.
Never rearm a closed validation ledger. Provision a new reviewed run/budget and
update both role routes and console guard binding before accepting paid work.

The local main console at `http://127.0.0.1:18120` has been rebuilt with these
bindings in the private override
`/root/.config/cyberguard/console-validation-001/console-live.override.json`.
It preserves its original data volume/users and waits for an armed budget before
new dispatch. Keep that override when recreating this particular local service:

```sh
docker compose --project-directory /mnt/d/Projects/CyberGuard/research-source \
  -f /mnt/d/Projects/CyberGuard/research-source/compose.yaml \
  -f /root/.config/cyberguard/console-validation-001/console-live.override.json \
  up -d --no-deps operations-console
```

Attempt 3 completed job `INV-56e68f7cac424c9a9c8c4d738658ab94` through investigator,
planner and verifier, each using one actual provider request. This successful
attempt used 20,590 input and 2,608 output tokens. Including two preserved earlier
attempts, total usage was 7 requests, 41,080 input and 6,722 output tokens. The final
guard is closed and drained. Its per-request output cap was 3,500 after the
earlier 2,000 cap truncated a planner response; the original aggregate ceiling
was never increased. Actual submitted material, reports, Matrix room messages,
request/response IDs, and guard ledgers were retained under the output plan.
