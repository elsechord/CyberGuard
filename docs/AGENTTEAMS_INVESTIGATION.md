# Evidence-bound investigation on AgentTeams

This integration is **prepared, not run**. No new AgentTeams server or model
credentials have been supplied. The local evidence/report API and deterministic
tests do not prove a model, Worker, native Task, or Skill was executed.

## Scope and permissions

Three distinct roles perform investigation, response planning, and independent
review. Each reads the original immutable evidence bundle. Reports contain
supported/refuted/inconclusive claims, evidence references, unknowns, collection
requests, and approval-required suggestions. This task does not execute actions.

| Configuration | Credential at Higress | Allowed operations |
| --- | --- | --- |
| `cyberguard-investigation-readonly.yaml` | `CYBERGUARD_API_TOKEN` | Read run evidence and reports |
| `cyberguard-investigation-report.yaml` | `CYBERGUARD_REPORT_TOKEN` | Submit a cited report |
| Operator only; no MCP registration | `CYBERGUARD_INVESTIGATION_INGEST_TOKEN` | Import bundles and create runs |
| Existing response workflow, outside investigation | executor bearer; separate human approval secret | Version-bound response proposals and approved execution |

Keep credentials in the authenticated Higress administration surface, never in
task files, Matrix messages, exports, or Worker prompts. The run ID in these MCP
tools is a logical scope, **not** an authorization boundary between customers.
Shared bearer tokens must not be treated as multi-tenant isolation. For a fair
blind comparison use an isolated gateway/data directory for each mode, so one
mode cannot read another's reports through the shared bearer token.

## Prepare locally

1. Collect or import a bundle with the evidence CLI and validate its hashes.
   Keep exercise answer keys outside the model-accessible gateway, workspace,
   container, and task package. A hash does not authenticate the collector.
2. As operator, import it with `POST /investigations/bundles` and create a run
   with `POST /investigations/runs`. Bind the exact bundle ID, mode, and aggregate
   `budget: {max_input_tokens,max_output_tokens,max_tool_calls}`. Follow the
   gateway's actual OpenAPI schema rather than embedding an ingest credential in
   a Worker. The gateway enforces tool quota; model token limits need runtime enforcement.
3. Generate a non-overwriting task package:

```powershell
python scripts/prepare-investigation-task.py --bundle artifacts/bundle.json `
  --out artifacts/task-multi --run-id investigation-multi-001 --mode multi_agent `
  --model YOUR_ACTUAL_MODEL --max-input-tokens 12000 --max-output-tokens 4000 --max-tool-calls 24
```

The package contains only `task.md`, `task-manifest.json`, `run-request.json`, and `SHA256SUMS`.
`run-request.json` is the exact JSON body for operator-only run creation, without credentials.
It deliberately does not copy an evidence directory, experiment generator, or
answer key. All modes receive the same evidence and tool/permission scope;
multi-Agent token budgets apply to all Workers combined, not to each Worker.
The manifest remains `status=not_run`, `usage=null`, `runtime_attestation=not_attested`.

## Connect after the server is available

The repository's established compatibility target is AgentTeams v1.2.2. The
new MCP definitions use the same Higress `requestTemplate` format as existing
definitions. `agentteams/investigation-workers.yaml` uses existing Worker CR
syntax and existing packaged Skills. It is an unapplied configuration example;
its inherited model identifier is **not** an assertion that the model is available.

Register the two narrow MCP definitions with the existing authenticated Higress
setup path. Do not expose the gateway's entire OpenAPI schema: it includes
operator-only import/run creation routes. Verify actual tool arguments and return
shapes against the deployed gateway before assigning the clients.

Build existing Worker packages with `scripts/package-agentteams-workers.py`.
Review the actual model/runtime/package availability and export existing Worker
CRs before applying the investigation configuration: its three names reuse
existing CyberGuard Workers and would replace their previous MCP assignments.
Verify real Worker configuration snapshots after application. The single-Agent
comparison requires one Worker with the union of the same Skills and the same
two clients; its package must actually contain those Skills. Do not claim a
single-Agent baseline was run merely because the task package was generated.

Use the existing Matrix room mechanism described in `agentteams/BOOTSTRAP.md`:
send the prepared task to the team room, addressing its real leader. The existing
`scripts/capture-agentteams-task.py` can capture the Matrix transport when supplied
the task file and correct room. Its incident snapshots concern the legacy
incident workflow; collect the new run evidence/report endpoints separately.
Matrix chatter, the request event ID, or an Agent's own "completed" message alone
does **not** prove native Task completion, tool execution, or Skill lifecycle.

GET evidence returns `{run,bundle,tool_receipt,notice}`. POST reports accepts the
report JSON directly and returns the report plus structural validation and a
tool receipt; these are gateway receipts, not AgentTeams runtime attestation.
GET reports returns run/report/receipt data. Preserve all responses unmodified.

The existing response MCP now carries `run_id` and `model_mode`. In `host_lab`,
`terminate_process` and `disable_persistence` targets must be the complete
original `target_ref` from fresh observation; never reconstruct PID/path/versions.
No MCP exposes `/actions/approve` or the human approval secret. Old evidence
bundles are insufficient for a fresh destructive-action decision.

## Runtime evidence gate

`scripts/validate-investigation-run.py evidence/manifest.json` validates a local
review manifest with schema `cyberguard-agentteams-run-evidence/v1`. It does not
guess unobserved AgentTeams exporter fields or call an invented Task endpoint.
An operator maps fields in preserved raw JSON exports using JSON Pointers:

```json
{"source":"task-export","pointer":"/spec/actualFieldObservedOnTheServer"}
```

The pointer above illustrates syntax only, **not** an AgentTeams API field.
Each `sources` entry has `id`, relative `path`, file `sha256`, and one kind:
`native_task`, `native_workers`, `native_tool_events`, `native_skill_events`,
or `native_model_usage`. Paths must remain under the evidence directory. Do not
rewrite originals to make validation pass. If the deployed exporter lacks a
required field, record the gap and extend a reviewed adapter after inspecting
the real format; do not fabricate receipts.

The manifest has `run_id`, `bundle_sha256`, `mode`, aggregate `budget`, and:

| Field | Required source-backed entries |
| --- | --- |
| `task` | `task_id`, `run_id`, `bundle_sha256`, `status` |
| `workers[]` | literal role name plus references `worker_id`, `skills` string array, `tools` client-name array |
| `tool_calls[]` | `worker_id`, `task_id`, `run_id`, `bundle_sha256`, `tool`, `call_id` |
| `skill_events[]` | `worker_id`, `task_id`, `skill`, `event_id`, `phase` |
| `usage` | `task_id`, aggregate `input_tokens`, `output_tokens`, actual `model` |

Every runtime field above must be a source/pointer object, not a literal copied
from the task prompt. The role labels are operator mappings; they are checked
against source-backed Skill configuration. Multi-Agent mode needs three distinct
Workers. Each must read evidence; a report submission receipt is required. At
least one same Skill per Worker must have `loaded` and `invoked` events for the
same native Task. Mere installed configuration is insufficient. The narrow
status vocabulary is `Completed`, `Succeeded`, `completed`, `succeeded`; unknown
exporter vocabularies fail closed pending a reviewed adapter. Actual model usage
must be positive and within the declared aggregate budget.

Success is deliberately named `structurally_complete_not_attested`. SHA256 and
operator-declared source kinds cannot prove the exports came from a real server.
Authenticity still requires retaining collection provenance and inspecting or
independently reproducing the run. Report semantic correctness and independent
review quality need separate evaluation; this gate does not establish them.

## Validation performed locally

`python tests/test_investigation_agentteams.py` checks task isolation, no-overwrite
behavior, literal/self-reported runtime rejection, absent Worker read/Skill/usage
evidence, cross-run bindings, budget limits, tampered sources, path traversal,
and the distinction between structural consistency and attestation. Synthetic
test exports are never labeled as an actual AgentTeams run.
