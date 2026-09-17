# Fresh identities behind model admission

This is a deterministic, serial harness integration of three real AgentTeams
Workers. It is not a demonstration of autonomous room creation/delegation, and
does not establish a fair comparison with single-agent or fixed workflows.
The earlier Workers and evidence remain stopped and preserved.

## Source-verified model path

Upstream AgentTeams v1.2.2 commit
`849182af8e017168a5a200a87b1062142caf462d` supports `Worker.spec.modelProvider`.
`internal/gateway/higress.go:ResolveModelProvider` selects the route for that
provider and builds the Worker's gateway base URL from its prefix.
`EnsureModelProviderAuth` calls `AuthorizeAIRoutes` with a provider filter;
`modifyAIRoutes` removes that consumer from nonmatching provider routes.
The generic provisioning step initially authorizes all AI routes, so readback
after reconciliation is mandatory. Do not send tasks during preparation.

The intended chain is:

```
new Worker role alias + Worker Higress key
  -> /cg-guard/<new-role>/v1/chat/completions
  -> one role-specific Higress OpenAI-compatible provider
  -> http://model-guard.agentteams.local:8080/v1/chat/completions
     (provider Authorization replaced with immutable role/run guard key)
  -> original provider, whose key is held only by the guard
```

WorkerEnvBuilder provides Worker-specific Higress, Matrix, and storage credentials;
it does not propagate `AGENTTEAMS_LLM_API_KEY`. This source fact is not sufficient
on its own: inspect each new container/config and test rejection of its key on
the old direct-provider route before arming. Never print keys in audit output.
The existing Controller still has its old provider configuration for legacy
identities; do not claim the entire deployment has no direct-provider route.

The installed QwenPaw OpenAI provider explicitly creates its chat model with
`stream=True`. `max_tokens` comes from provider/model settings and may be unset.
The guard must cap each request and provide compatible SSE; prompt instructions
and a periodic usage monitor cannot substitute for admission. Disable native
LLM retries, background titles and memory generation for these new identities.

## Prepared files and execution order

Run these scripts inside WSL. Preparation is offline and refuses an existing
output directory. It packages existing Skills without editing their text.

```bash
python3 deploy/agentteams-local/prepare-guarded-team.py \
  --out /mnt/d/Projects/CyberGuard/output/agentteams-guarded-preparation-005 \
  --run-id AT-INV-20260917-005 --name-prefix cg-inv005 \
  --model deepseek-v4.1-flash \
  --guard-url http://model-guard.agentteams.local:8080/v1
```

The plan contains three Sleeping Worker CRs, a new Team with peer mentions and
leader heartbeat disabled, per-role packages, provider/route templates and hashes.
The roles are `investigator`, `planner`, `verifier`. Model aliases are
`cg-inv005-<role>-model`. The private guard config must match them exactly.

Only after the guard is running **disarmed**:

```bash
python3 deploy/agentteams-local/register-guarded-routes.py --plan PLAN_DIR
python3 deploy/agentteams-local/apply-guarded-team.py \
  --plan PLAN_DIR --out NEW_SLEEPING_DEPLOYMENT_AUDIT.json
python3 deploy/agentteams-local/authorize-guarded-mcp.py \
  --plan PLAN_DIR --out NEW_MCP_CONSUMERS_AUDIT.json
```

Registration reads `/root/.config/cyberguard/model-guard.env` (owner-only), parses
`CYBERGUARD_MODEL_GUARD_CONFIG`, and sends only the needed role keys over stdin
into the trusted Controller. It refuses to replace existing route/provider names.
The deployment script checks new identity names and package hashes, creates
Sleeping Workers first, uploads their packages through the official CLI, and
checks that their model/state remained correct. It never wakes or arms anything.
Each role needs its own Higress DNS service-source name even when all point to
the same guard endpoint; Higress does not bind one instance to multiple providers.
The MCP authorization step replaces only the two investigation servers' consumer
lists with the three fresh Workers. It does not rewrite secret backend YAML.
The Controller may add its Manager consumer to AI routes automatically; keep the
old Manager stopped throughout this run and audit each new Worker's route scope.

When the operator starts only those new identities for API configuration, keep
the guard disarmed and send no Matrix task. Then run:

```bash
python3 deploy/agentteams-local/configure-guarded-runtime.py \
  --plan PLAN_DIR --out NEW_RUNTIME_POLICY_AUDIT.json
python3 deploy/agentteams-local/fix-native-guard-host.py \
  --plan PLAN_DIR --out NEW_NATIVE_HOST_AUDIT.json
```

This uses the installed native management API to disable all configured built-in
tools (including shell, file editing, browser, web and subagent spawning), disable
non-investigation MCP clients (including TeamHarness and WorkerFlow), and allow
only the three named investigation tools on the two narrow MCP clients. Unlike
the failed prior Matrix-specific rule, these exact tool rules do not depend on
possibly missing request-context channel fields. Other tools default to deny.
The before state is persisted before mutation and the final configuration is read
back. This is tool configuration for a trusted local runtime, not hostile-code
isolation or network egress containment.

Every container reconstruction requires this hardening and fresh schema audit.
The upstream wrapper enables TeamHarness/WorkerFlow again during startup. Its
`/api/version` readiness check also precedes complete Workspace startup: two MCP
connections can each consume a 30-second timeout while the wrapper uses a
10-second API timeout. A version response therefore does not establish that
workspace-scoped GET/PUT endpoints are ready. Retain failed containers and logs;
do not repeatedly restart or infer success from the Controller's Running phase.

The release's embedded-mode config replaces the AI gateway host with the
Controller host. For custom model-provider routes, that produced an HTTP 405
before the request reached the guard: the existing Envoy virtual host was
`aigw-local.agentteams.io`. `fix-native-guard-host.py` updates the native
`agentteams-gateway` provider through its documented API to that existing explicit
host while preserving the role prefix and Worker credential. This is a local
deployment adaptation and must be repeated after reconstruction. Adding an
unregistered domain to a route's console JSON alone did not update Envoy's virtual
hosts. Do not treat the console JSON readback as a data-plane test.

The dynamic `Skill` loader is separate from the built-in list. Verify its actual
inference schema before selectively allowing it. Do not claim that an installed
Skill was invoked without native lifecycle/tool evidence. TeamHarness's available
Skills may still be described in context even when its MCP tools are disabled;
the model-facing schema audit must distinguish descriptions from capabilities.

## Mandatory preflight and serial dispatch

Before arming, collect all of the following without a paid request:

1. Every new Worker consumer is authorized only on its role guard route; attempts
   to the original provider route and another role's route are rejected.
2. A valid request through each role route reaches the disarmed guard and returns
   `guard_not_armed`; this proves routing without charging the upstream provider.
3. Native configuration and the actual inference tool schema contain no shell,
   browser, spawn, roomflow or arbitrary network tools. Confirm the allowed Skill
   loader separately if it is retained.
4. Guard rejection covers missing/mismatched role keys, request count, duplicates,
   concurrency and closed runs. No request is queued for later automatic payment.
5. Container/config audits find no original provider key in the new Workers;
   console ports remain localhost. New identities have no prior conversation.

Use `audit-guarded-routing.py --plan PLAN_DIR --out NEW_AUDIT.json` for ACL and
blocked HTTP probes. Use `probe-guarded-schema.py --plan PLAN_DIR --out NEW_PROBE.json`
only while disarmed, then inspect the guard's `declaration-<role>.json` files.
The latter uses separate console sessions whose IDs/digests are exported, never
the formal Matrix task rooms. It does not call investigation tools or spend the
fresh gateway run's quota. No provider inference is authorized by these scripts.
Run 004 was permanently closed at zero upstream requests and must not be reused.

For the local 005 preparation, `routing-audit-6.json` records all three own routes
returning `guard_not_armed` and legacy/sibling routes rejecting credentials.
`runtime-policy-final-audit-2.json` is the final complete native configuration
readback after reconstructing the investigator container; earlier partial audit
files are retained. `native-schema-probes.json` records three separate console
sessions and response hashes. The declarations still require explicit inspection
before arming; an HTTP 200 streaming response alone is not evidence that the
expected tool schemas reached the guard.

The operator's serial harness should deliver one task event to the investigator's
own native Matrix room, await its real evidence-read and report, then invoke the
planner and finally the verifier in their own rooms. Each role must read the
fixed evidence independently. Carry previous actual report identifiers, never
operator-filled findings, into later stages. Stop on a stage failure; do not
resubmit automatically. Match Matrix event IDs, native Worker history, guard
request IDs and gateway receipts. The shared guard, not the prompt, controls
the total request budget and permits at most one upstream call at a time.

This sequence deliberately avoids autonomous `roomflow` and self-message tools.
Earlier native history contained the same user message twice in one session
within 31.6 ms and two nearly concurrent model turns, as well as invitation-array
type errors. Fresh identities isolate history but do not prove duplicate delivery
is fixed. An over-budget or partial run must remain a failure/partial result.

No preparation file or successful policy PUT constitutes a completed three-agent
task. Completion still requires genuine independent reads, outputs, validation,
usage and native task/Skill evidence appropriate to the claim being made.
