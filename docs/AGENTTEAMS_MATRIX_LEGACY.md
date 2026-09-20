# Legacy Matrix serial backend (historical)

Select explicitly with `CYBERGUARD_AGENTTEAMS_BACKEND=matrix`. New deployments use [native Tasks](AGENTTEAMS_TASK_SERVICE.md).

The console bridge sends work to three actual AgentTeams Worker Matrix rooms in
order: investigator, planner, verifier. All reasoning and report writing happen
inside those Workers. The bridge transports original materials and actual prior
Worker reports, validates citations, and persists transport receipts. It never
calls a model provider itself or constructs findings locally.

Configure the console service with these private server environment variables:

| Variable | Meaning |
| --- | --- |
| `CYBERGUARD_AGENTTEAMS_MATRIX_URL` | Reachable Matrix origin, e.g. `http://agentteams-controller:8080` on the private Docker network |
| `CYBERGUARD_AGENTTEAMS_MATRIX_HOST` | Optional required virtual Host, locally `matrix-local.agentteams.io:18080` |
| `CYBERGUARD_AGENTTEAMS_MATRIX_TOKEN` | Existing Matrix bearer credential; preferred to password login |
| `CYBERGUARD_AGENTTEAMS_MATRIX_USER` / `CYBERGUARD_AGENTTEAMS_MATRIX_PASSWORD` | Password login fallback when token is absent |
| `CYBERGUARD_AGENTTEAMS_ROLES_JSON` | Fixed mapping of all three role names to `{ "room_id": "!actual:server", "sender_id": "@actual:server" }` |
| `CYBERGUARD_AGENTTEAMS_STAGE_TIMEOUT_SECONDS` | Each stage deadline, default 300 seconds, bounded 30–3600 |
| `CYBERGUARD_AGENTTEAMS_PROMPT_MAX_BYTES` | UTF-8 prompt limit, default 48 KiB; additionally the complete event must fit the conservative 60 KiB envelope limit |

Use actual Worker `roomID` and `matrixUserID` from `agt get workers -o json`.
The configured Matrix account must already belong to those rooms. Keep tokens
out of task inputs, browser state, reports, logs and exports. Use separate Worker
identities and a controlled model route for this task service; earlier benchmark
runs and their closed model budgets must not be reused.

The caller must durably save **every** `advance(job)` result before another
advance, and dispatch only one job at a time. Preparation saves a Matrix sync
cursor in one transition; the next transition sends a stable job/role transaction
ID. A crash during send is retried with the same transaction and preserved cursor,
so Matrix deduplicates it. Room messages are paged forward from that cursor.
Keep the same persistent bearer across restarts: Matrix transaction deduplication
can be scoped to the token. A persisted non-secret token fingerprint makes the
bridge fail closed if that credential changes during a job. Password fallback
caches tokens for five minutes in memory; restarting it mid-job may require
operator reconciliation. Deployment should provision a persistent bearer.
Only messages from the configured Worker with the exact job ID and role in a
structured report are eligible. Supported/refuted findings require a material ID
and exact quote from that original material. This validates evidence references,
not truth of the inference. The verifier still performs the independent review.
Native reasoning messages can mention report delimiters; only an entire final
report message is parsed, including Matrix's edit fallback prefix. JSON duplicate
keys and non-finite numbers are rejected.

These fixed Worker rooms retain their conversational context across jobs. API
ownership checks do not provide strict tenant isolation inside that shared
AgentTeams runtime. Deploy dedicated rooms/Workers and credentials for customers
requiring isolated model context; do not advertise the shared local deployment
as a multi-tenant security boundary.

Unavailable or missing connections produce `waiting_backend`; invalid reports
fail closed. No fabricated successful report is substituted. The public runtime
classification is `agentteams_worker_orchestration`; native Task completion stays
`not_attested`. AgentTeams v1.2.2 commit
`849182af8e017168a5a200a87b1062142caf462d` has no controller task/project REST API.
Newer cached source APIs must not be assumed available on that pinned deployment.

Worker report transport uses Matrix login, `/sync`,
`PUT /rooms/{room}/send/m.room.message/{transaction}`, and `GET /rooms/{room}/messages`
under `/_matrix/client/v3`. Controller Worker lifecycle is separate:
`POST /api/v1/workers/{name}/wake`, `/sleep`, `/ensure-ready`, and
`GET /api/v1/workers/{name}/status`. A Running Worker does not prove workspace
readiness or task completion. Preserve response event IDs and Worker identities.

This console path passes normalized materials directly to Worker prompts. It does
not currently import an immutable investigation gateway bundle or attest native
Skill invocation, gateway tool receipts, native task IDs, or provider token usage.
Those remain separate evidence gates described in AGENTTEAMS_INVESTIGATION.md.

Local inspection on 2026-09-20 initially found old Workers stopped and no
controller. Offline read-only inspection of the preserved controller database
confirmed all old Worker and Manager desired states were Sleeping. The pinned
controller was then restored with the localhost patch and Manager disabled.
Fresh `cg-console001` Workers use a separate disarmed guard and budget ledger;
old workloads remain asleep. Initial fresh Worker startup reproduced the known
QwenPaw readiness timeout. Those failed containers were preserved and the existing
pinned readiness patch was built and applied only to fresh Workers. Native policy
readback shows no enabled built-in or MCP tools, no retries or background model
features. Separate disarmed inference probes reached the guard with empty console
tool declarations and no forwarding; own-route admission and sibling/direct-route
rejection were checked. These preparation checks are not a completed paid task.
See `deploy/investigation-service/` for the bounded local validation helpers.
Unit fixtures exercise transport and validation only, not runtime execution.

The subsequent actual three-Worker validation completed successfully; see the
[validation record](INVESTIGATION_SERVICE_VALIDATION.md) for the task ID, retained
failed attempts, model usage, Skill checks, and current paused-budget state.

The subsequent real HTTP validation completed job
`INV-56e68f7cac424c9a9c8c4d738658ab94` through all three native Workers. The exported
report has original-material exact quotes, three distinct Worker identities,
and Matrix request/response event IDs. The verifier explicitly treated the
embedded instruction to assert attacker attribution as untrusted input.
Idempotent submission returned the same job. The successful attempt consumed
3 model requests, 20,590 input and 2,608 output tokens. Across the initial parser
failure, the canceled output-truncation attempt, and the successful attempt,
total usage was 7 requests, 41,080 input and 6,722 output tokens, within the original
9-request/150,000-input/12,000-output ceiling. All ledgers and prior terminal
states were preserved. The final guard was closed with no in-flight reservation.
Artifacts are under `output/console-agentteams-validation-001/attempt3` in the
local parent workspace. This establishes Worker orchestration and real model
execution, not native Task/Skill attestation or general report semantic accuracy.

Run `python -m unittest discover -s tests -p test_agentteams_bridge.py` for bridge
tests, including crash retry, independent sender filtering, forged quote rejection,
configuration binding, backend outage, and the complete three-Worker sequence.
