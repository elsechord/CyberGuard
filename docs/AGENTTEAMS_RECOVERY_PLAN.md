# Native AgentTeams recovery: observed failures and bounded acceptance

This plan is based on the preserved `output/agentteams-local-20260917/native-history-003`
exports. It does not resume Workers or authorize another model request. The
snapshot demonstrates partial integration, not completed three-role work.

## What the native history establishes

Source: `response-planner-history.json`, row `seq` numbers below. Its exported
SHA-256 is `c32f162ede02e61acda6aa963469ebb2dcf9ed8b545c631743124df10fab1d63`.

| Evidence | Finding |
| --- | --- |
| 28, 29, 31, 35 | `roomflow.create_task_room` rejected `invite` because the model supplied a string. Variants included a JSON-encoded array, comma-separated users and duplicate `invite` keys. The tool requires an actual JSON array. |
| 30 | `payload` was a JSON string; the tool requires an object. |
| 32 | An actual array of two Matrix users succeeded and created room `!8oG3gtAujMgdcFyoeC:matrix-local.agentteams.io:18080`. |
| 34 | A subsequent creation without invites returned the same room with `reused=true`. It was not a second independent task. |
| 14, 20, 39, 41 | `driver_policy_denied` identifies `mcp-cyberguard-investigation-readonly`, operation `invoke`. These are native driver-policy denials, not a CyberGuard HTTP 401/404 report. |
| 17 | A different call of the same evidence tool for run `AT-INV-20260917-003` succeeded and contains the immutable bundle and a gateway receipt. The route was not universally unavailable. |
| 11 and 12 | Identical user content in the same Matrix session was recorded twice, 31.602 ms apart, with different dedup keys. |
| 13 and 16 | Two distinct model turns followed, 227.499 ms apart. One branch contains denied reads; the other contains the successful read. |
| 37–43 | The task-room self-trigger starts another Leader turn. Its two reads were also denied, so the original room's successful read does not prove task-room policy readiness. |

The duplicate content at rows 11/12 is concrete evidence of duplicate native
context ingestion. It does not identify whether the source was two delivery
adapters, retry handling, queue replay, or a runtime session race. The policy
exports exercise a constructed `channel=matrix` context. They do not prove that
every actual tool invocation carried that context. Inspect native invocation
context and policy snapshot for each specific call ID before assigning a more
precise cause. Do not solve this by globally allowing all drivers.

The history contains earlier run 001/002 user messages in the same team session.
Their timestamps precede run 003. No exported evidence-tool input for an old run
appears after the first run-003 context. Therefore **old history is retained, but
execution of an old queued task during run 003 is not established by this
snapshot**. A queue-empty check still requires native pending-job/state inspection.

The other Workers did not reach their investigation tasks. Endpoint-forensics
has only context, model narration and Skill results; recovery-verifier inspected
rooms and waited for `TASK_ASSIGNED`. Neither export contains a successful direct
evidence read. No role export contains a successful `taskflow`/`projectflow`
operation or accepted investigation report. Creating a Matrix task room is not
creating and completing the native assigned work.

## Before spending more model tokens

Prepare a fresh attempt with a new run ID, fresh task room/session, new task IDs
and an isolated native workspace. Preserve the old volumes/exports for audit.
Keep old Workers stopped. Confirm native pending work cannot be replayed into the
new attempt; merely adding “ignore the old run” to a prompt is insufficient.

Use operator-side deterministic setup for room membership and the native task
specifications. Validate `invite` as an array, `payload` as an object and unique
JSON keys before any native API request. Do not ask the model to create or invite
rooms. Record that setup was operator-controlled; do not label it autonomous
planning by the model.

Complete no-model preflight against the **same native invocation path and
Matrix channel context** that the Worker will use. Check evidence read and report
submission policies separately for each of the three exact Worker identities.
Use a separate disposable preflight run for read/submit smoke tests, never the
measured investigation run. Verify returned run/bundle/receipt hashes. Test denied
shell/response operations with the policy evaluator without executing them. A
synthetic policy context alone is insufficient if the live adapter loses context.

Use exactly one event-delivery route for each assignment. Record the originating
Matrix event ID and prove it results in one native context entry and one active
turn. Do not combine automatic task notifications, manual mentions, and a
same-room `message` send. Check actual delivery and queue deduplication before
waking all roles. The stored delegation Skill says `delegate_task` already
notifies; `create_quick_project` does not. Keep these paths separate.

Inspect the available native tool schemas and estimate system/tool context size
before launching. Expose only the current evidence tools and the minimal native
task/Skill/artifact operations needed for the assigned work. Avoid room creation,
invitation, broad shell and unrelated project-management discovery. Three roles
may use different instructions, but should retain the same underlying evidence
and tool authorization for a later fair comparison.

## Shortest useful three-role acceptance flow

Use one fixed three-node dependency chain, prepared deterministically through
the real native project/task mechanism. Assign each role its own task directory.
The next node starts only after the prior native result is submitted and its
artifact location is known. These dependencies are workflow setup, not hidden
answers. Do not pre-populate findings, hypothesis decisions or reviewer verdicts.

1. **Endpoint investigator** acknowledges its actual native task, loads the
   relevant investigation Skill, reads the bound bundle directly and writes an
   evidence-cited investigation artifact. It distinguishes observations,
   competing hypotheses and missing evidence. It submits the native task result
   once and sends the protocol-required completion notification once.
2. **Response planner** receives that real result, independently reads the same
   original bundle, and produces a bounded response-plan/report draft. It must
   cite available evidence, avoid acting on CPU alone, and retain unknowns about
   initial access and attribution. Its artifact identifies the investigator
   artifact digest it used. It submits its native task result once.
3. **Independent verifier** directly reads the original bundle, then compares the
   actual investigator/planner outputs against it. It records specific supported,
   overstated and unresolved claims, with source-artifact digests. It submits a
   reviewed report through the real CyberGuard report tool and preserves the
   validation receipt. A separate review artifact explains changes; the operator
   does not edit findings to make validation pass. It submits its native result.

This avoids a fourth model turn solely to repeat the final report: the operator
can export the verifier's accepted report and native completion evidence without
writing new conclusions. If the configured native project requires Leader
acceptance, retain its native check/accept operation and receipt; do not silently
replace it with a handwritten “completed” flag. A failure ends the affected node
and blocks dependent nodes instead of broadcasting repeated room requests.

All three must actually execute the read themselves. A bundle copied from the
Leader's chat is not independent collection. The current gateway uses shared
bearer roles and does not independently identify each Worker: correlate each
gateway read receipt ID with the corresponding Worker's native tool result. Three
gateway reads alone do not establish three independent Workers.

## Evidence required to call the run complete

- The exact fresh run/evidence hashes, protocol, task room, three native task IDs
  and Worker identities; no cross-run results or duplicate delivery.
- Per-Worker native model execution and provider usage, real Skill invocation and
  a direct-read tool result matching a distinct gateway receipt.
- Three model-produced artifacts with native task-submission results, dependency
  references and the final reviewed report's actual gateway acknowledgement.
- Aggregate usage for all roles, retries and framework overhead, plus a terminal
  runtime state and preserved failure records if any gate fails.

Do not equate a model's “verified” sentence, a Matrix announcement, or the native
task room's name with these records. Hashes establish byte integrity, not truth
of an investigator's conclusions or independent runtime attestation.

## Budget and comparison boundary

Run 003 uses 150,000 input / 16,000 output tokens and 24 tools; the local
single-agent baseline used 20,000 / 8,000 / 16. This recovery is **integration
acceptance**, not an equal-budget model comparison. Do not change that statement
because one path eventually succeeds.

A subsequent comparison needs fresh held-out cases, identical evidence/tool
permissions, the same aggregate budget and explicit accounting of fixed native
framework overhead. Native task/artifact tools and deterministic orchestration
must be available/charged consistently; the single-agent baseline must not be
artificially denied a capability. Operator-written task setup is allowed as a
declared common harness; operator-written investigative answers are not.

## Offline checks available now

```sh
python scripts/preflight-agentteams-recovery.py --self-test
python scripts/preflight-agentteams-recovery.py --history-dir ../output/agentteams-local-20260917/native-history-003 --target-run AT-INV-20260917-003
python scripts/preflight-agentteams-recovery.py --room-request path/to/operator-room-request.json
```

The script uses only local JSON files, rejects duplicate JSON keys, checks the
observed room argument contract and audits native call/result rows without
executing any instructions in them. Its result explicitly says
`runtime_readiness=not_established`: passing these offline checks cannot attest
live policy context, delivery deduplication or queue isolation.
