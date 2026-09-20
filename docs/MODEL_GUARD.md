# Local model admission guard

[简体中文](MODEL_GUARD.zh-CN.md) · [中文文档导航](README.zh-CN.md)

The local AgentTeams integration routes each fresh Worker's dedicated Higress provider to this guard before any paid provider request. This replaces after-the-fact polling as the primary request admission control. This component is an experimental single-process local service, not a complete multi-tenant model gateway.

## Fixed identity and limits

`scripts/prepare-model-guard.py` generates distinct operator and role credentials in private POSIX files. The original provider key remains on the operator/guard side. A role key fixes a run, role, model alias and exercise evidence hash; caller-supplied request IDs do not change these bindings. The SQLite ledger and full configuration hash reject changes to an existing run. Rotation requires a new run; retain the old run and its accounting.

The current integration template allows nine provider requests total, three per role, one concurrent request, 300,000 input tokens and 24,000 output tokens in the ledger, with a 6,000-token output cap per request. Limits are test settings, not a pricing estimate or model capability claim. A full request's serialized UTF-8 byte length plus 2,048 is reserved as input. This is a conservative heuristic, **not a verified tokenizer upper bound or a guaranteed monetary cap**. Actual provider-reported usage settles reservations; an overrun halts the run. Upstream token fields may not reflect the provider's final invoice.

Identical normalized requests from the same role cannot be forwarded twice, including across service restarts. This is exact payload deduplication, not semantic duplicate detection. Budget and concurrency reservation uses a SQLite transaction before dispatch. No automatic provider retry is performed. Busy requests fail without an internal queue. Two repeated structured failures for the same tool/error fingerprint halt the run.

Closing is ordered against dispatch by an in-process lock and an atomic ledger transition. A call already committed to dispatch cannot be recalled. A timeout, missing usage or persistence failure retains its reservation and stops further admissions. Pending/unknown requests have no timeout-based release. Restart always disarms the service; uncertain reservations prevent rearming.

## Operator sequence

Run the following inside the private WSL/Linux operator environment. Do not put credentials in command arguments, repository files or output artifacts.

1. Generate a new private configuration using `scripts/prepare-model-guard.py --bundle benchmark/investigation/cases/case-001.json --run-id <new-id> --name-prefix <new-prefix> --model-env /root/.config/cyberguard/agentteams-llm.env`. Existing files are never overwritten. Archive prior closed-run configuration privately before creating another run.
2. Build `services/model-guard/Dockerfile` as `cyberguard/model-guard:local`, then start `compose.model-guard.yaml`. Its default private env file is `/root/.config/cyberguard/model-guard.env`. The host listener is loopback port 18110; AgentTeams reaches the guard over the Docker network.
3. Keep the service disarmed while checking actual Worker runtime tools, dedicated providers, route consumer allowlists, empty queues and disabled automatic/background model calls. Stop old Workers and Managers which could bypass this guard.
4. Use `python3 scripts/control-model-guard.py status` to verify the run binding and zero usage. A disarmed model request records only tool names and definition hashes, then rejects the request without forwarding. `GET /v1/models` also stays local.
5. Only after preflight succeeds, use `python3 scripts/control-model-guard.py arm`. Send one bounded role task at a time. Use `close` to finish the run permanently and retain the ledger and evidence.

The control script accepts `--output <new-file>` for an operator snapshot. After closing, use `python3 scripts/export-model-guard.py --output <new-directory>` to export that run's ledger metadata, traces and source/export hashes. Unknown in-flight usage can still settle later, so retain the snapshot's uncertainty. The data volume contains `admission.sqlite`, request records and disarmed tool declarations. Do not reset or delete it to make a failed run appear successful.

## Tool and transport boundary

Role configurations allow the dynamic `Skill` tool and the three investigation MCP functions (read evidence, read reports, submit report). Actual runtime declarations must match before arming. The guard rejects unallowed request tools and provider calls to tools not declared in the request. This does not revoke independent runtime access to shell, files, network or other model providers: those must be disabled and verified in AgentTeams/Higress separately.

The upstream request is buffered, with `stream=false`; an SSE-compatible response is synthesized only after usage settlement. This is not incremental streaming. Responses are bounded at 4 MiB and requests at 1 MiB. The provider socket I/O timeout is 90 seconds, not an overall wall-clock deadline: a slowly progressing response may take longer and retain the only in-flight slot. Closing the run stops new work but cannot recall that dispatched request. There is no per-user isolation or distributed-service failover in this deployment.

Stored traces replace known credential literals and a finite set of JSON-escaped forms. This is not a general secret detector or a guarantee against arbitrary encodings. Treat trace storage as sensitive and scan exports before publication. The guard's evidence hash binds accounting metadata; it does not by itself restrict which evidence a generic MCP endpoint can read. The current shared MCP integration is a trusted local exercise, not a blind evaluation or a cross-run security sandbox.

## Validation scope

`tests/test_model_admission.py` covers immutable run bindings, atomic budgets, independent processes, crash/unknown reservations and usage settlement. `tests/test_model_guard.py` uses fake transports to exercise request bounds, dispatch/close races, deduplication, role authentication, tool restrictions and failure behavior without paid calls.

Three real native Workers run in an operator-controlled serial harness to test integration. Successful reports would demonstrate actual Worker → model → MCP → gateway execution. They would not establish autonomous task planning, fair multi-agent performance gains, production readiness or attribution to a real threat organization.

## Native AgentTeams tool policy

Set `tool_policy` to `runtime` when AgentTeams owns tool authorization. The guard still checks model identity and reserves request/token budgets, but does not duplicate the runtime tool allowlist or close the run after repeated tool errors. The default `guard` mode retains the fixed allowlist behavior for existing deployments.
