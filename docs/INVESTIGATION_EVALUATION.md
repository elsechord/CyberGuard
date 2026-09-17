# Evidence investigation and fair comparison

This is a working **fixed-workflow baseline**, plus a shared report contract and
an import interface for future real single-agent and multi-agent runs. It is not
an autonomous investigation or a cryptomining detector. No model/AgentTeams run
is inferred from producing a valid report.

## Run the offline baseline

From the repository root, with Python 3.12+ (no extra dependencies):

```sh
python scripts/investigate-evidence.py benchmark/investigation/cases/case-001.json --output artifacts/investigation/case-001
python scripts/evaluate-investigation.py benchmark/investigation/cases/case-001.json --rubric benchmark/investigation/evaluator-only/case-001.json --output artifacts/investigation/case-001-evaluation.json
python tests/test_investigation_analysis.py
```

Repeat for case-002 and case-003. Report generation produces both `report.json`
and a human-readable `report.md`. These commands neither call a model nor execute
a proposed response action.

| Exercise | Available observations | Expected cautious behavior |
| --- | --- | --- |
| case-001 | High CPU, temporary executable path, matching persistence configuration | Raise a suspicious-persistence hypothesis; preserve the distinction between configuration and active scheduler behavior. |
| case-002 | High CPU and supplied asset-owner workload inventory | Record the inventory match, avoid treating high CPU alone as an attack; do not declare the host clean. |
| case-003 | High CPU, persistence inaccessible, relevant authentication window missing | Leave workload classification unresolved, request missing observations, avoid destructive response. |

All three are **authored synthetic exercises**. The network addresses use
documentation ranges. These are not malware samples, recorded victim data, real
mining traffic or independent field-validation cases. Every bundle explicitly
declares `provenance.kind=exercise`.

## Inputs and the fixed rule

The shared evidence module validates each artifact SHA-256 and the complete
bundle SHA-256. These hashes detect changed bytes; they do not authenticate a
producer or prove observations are true.

The baseline correlates a measured CPU sample of at least 40% with the same
absolute executable path in a persistence command. Paths beneath `/tmp`,
`/var/tmp` and `/dev/shm` add a suspicious-location signal. An explicitly disabled
persistence entry is not positive support; `enabled=null` means scheduler state
was not established. The rule does not key on exercise filenames, PIDs, binary
names, ports, labels such as `malicious`, or evaluator answers.

It is deliberately limited: interpreter arguments are not collected by default
to avoid leaking secrets; a script launched through an interpreter may therefore
not match its executable. Low-CPU, in-memory, stolen-account and many other
intrusions are not covered. Configuration does not establish which parent
launched a process. CPU alone does not establish mining. Supplied inventory is
counterevidence to review, not proof of binary authenticity.

Authentication/network observations remain available to model-based or human
investigators, but this fixed rule does not parse arbitrary log prose into an
initial-access claim. Both entrypoint and organization attribution remain
inconclusive. Missing artifacts are not converted into negative evidence.

## Report contract and trust boundary

`cyberguard_investigation.analysis.analyze_bundle(bundle, run_id=None)` returns:

```json
{
  "schema": "cyberguard-investigation-report/v1",
  "bundle_id": "...",
  "bundle_sha256": "...",
  "mode": "fixed_workflow",
  "findings": [{
    "finding_type": "suspicious_persistence",
    "claim": "A specific, bounded claim",
    "status": "supported",
    "supporting_evidence_ids": ["EV-..."],
    "contradicting_evidence_ids": [],
    "limitations": ["Why this does not establish malware identity"]
  }],
  "unknowns": ["Initial access vector"],
  "next_collection": ["Request the missing incident-window logs"],
  "proposed_actions": [{
    "action": "review_persistence_and_preserve_binary",
    "target": "/example/path",
    "reason": "Review correlated observations before containment",
    "evidence_ids": ["EV-..."],
    "requires_approval": true
  }]
}
```

`mode` also permits `single_agent` and `multi_agent`. `run_id` is optional in a
portable report; a gateway must bind it to the immutable run it owns. A report
must not self-authorize an execution or change its run's mode.

`report.validate_report(report, bundle, expected_mode=...)` raises `ValueError`
on mismatched bundle ID/hash, mode, unknown/unavailable references, a supported
claim without support, a refuted claim without contradiction, or an action that
does not require approval. Inconclusive claims explain limitations. One artifact
can contain both supporting and contradicting observations; interpretation still
needs review. Schema validation **cannot verify the truth of a claim or that its
citation entails it**. A compromised model can still produce fluent nonsense
with valid evidence IDs. Such reports require semantic review.

## Comparison protocol and real-run imports

Generate the protocol **before** running any model:

```sh
python scripts/evaluate-investigation.py benchmark/investigation/cases/case-001.json --protocol-only --output artifacts/investigation/case-001-protocol.json
```

The protocol binds the exact evidence hash, identical task, tools
`read_evidence_bundle`/`submit_investigation_report`, read-only permissions, and
shared input/output token and tool-call ceilings. The default ceilings are
20,000 input tokens, 8,000 output tokens and 16 tool calls, aggregated across
**all roles** of a multi-agent run, including retries. These are comparison
settings, not a claim the runtime enforced them. Report unknown cost/time/token
measurements as `null`, never zero. The fixed workflow uses no model tokens.

A model run record has this import shape:

```json
{
  "mode": "single_agent",
  "status": "completed",
  "bundle_id": "copy from protocol",
  "bundle_sha256": "copy from protocol",
  "protocol_sha256": "copy from protocol",
  "report": {},
  "usage": {
    "input_tokens": null,
    "output_tokens": null,
    "tool_calls": null,
    "elapsed_seconds": null,
    "cost_usd": null
  },
  "execution_evidence": "location and digest of actual runtime receipts"
}
```

Replace `report` with the full evidence-bound report. The sample above is a
contract illustration, **not a completed run**. Import with `--import-run FILE`
(repeat for the other mode). `evaluation.validate_run_record` rejects changed
bundle/protocol/mode and invalid usage. Over-budget runs are retained and marked
`exceeded`; missing measurements are `unknown`. External receipt metadata stays
`caller_reported_not_independently_attested` until someone verifies the runtime
evidence. An imported JSON file is not proof a model executed.

With no imports, single-agent and multi-agent results are `not_run`, with no
score or usage fabricated. Do not present a comparison winner at this stage.

## Keep answers outside the agent boundary

Only give an evaluated agent the case bundle through the read-only tool. Do not
give it repository-shell access, the evaluator's directory, this case-answer
table, the exercise builder, fixed-workflow reports, or another run's output.

`benchmark/investigation/evaluator-only/` holds separate expected observations;
`build_exercises.py` is a maintainer-only generator. Neither belongs in an agent
image or accessible mount. This separation must be enforced by the runner: a
directory named `evaluator-only` is not an access-control mechanism. Exercise
source is publicly inspectable, so these three cases cannot establish blind
generalization. Create fresh held-out cases and an independent reviewer before
claiming comparative effectiveness.

The current scorer checks typed conclusion/status, required citation IDs,
absence of asserted entrypoint/actor identity and inappropriate state-changing
suggestions. Its pass count is a **small contract/behavior rubric**, not an
investigation accuracy percentage. It cannot judge whether natural-language
reasoning is adequate. Field evaluation still needs independent semantic review,
more cases, false-positive/omission measures, actual token/cost/time receipts and
human-review time. Single-agent runs must receive the same tools and permissions;
do not create a multi-agent advantage by artificially denying them operations.

## Actual single-model runtime (not AgentTeams)

`scripts/run-investigation-model.py` performs real OpenAI-compatible Chat
Completions requests and executes a model-selected tool loop. Its allowlist is
exactly `read_evidence_bundle` and `submit_investigation_report`. The first tool
provides the bundle; the second validates the model's complete report against
that same bundle and `mode=single_agent`. No shell, web, filesystem-search,
response-execution or evaluator tool is exposed to the model. The runner never
imports the fixed-rule analyzer or an expected-answer file.

The initial authorized experiment permits **exercise bundles only**. Importing
`live_collection` or `import` provenance fails before any network call.

```sh
python scripts/run-investigation-model.py \
  --bundle benchmark/investigation/cases/case-001.json \
  --output artifacts/live-single/case-001 \
  --endpoint https://YOUR-EXPLICIT-ENDPOINT/v1/chat/completions \
  --model YOUR-MODEL \
  --env-file /secure/location/model.env
```

The env file is parsed as values, never executed. It accepts
`CYBERGUARD_MODEL_API_KEY`, `AGENTTEAMS_LLM_API_KEY` or `OPENAI_API_KEY`. Keep this
file outside the repository and restrict its permissions. The explicit HTTPS
endpoint is fixed for the run and cannot be changed by model text; embedded
credentials, query strings and redirects are rejected. Error responses are not
copied to logs. Known credentials are removed from saved artifacts if a provider
ever echoes them.

By default, the two functions execute locally and traces say
`local_allowlisted_functions_not_agentteams`. To use an existing gateway run,
pass `--gateway-url http://127.0.0.1:PORT --run-id RUN` and provide distinct
`CYBERGUARD_API_TOKEN` and `CYBERGUARD_REPORT_TOKEN` values outside model context.
Create/import the bundle and immutable single-agent run separately. The runner
does not receive the ingestion credential. Gateway evidence must match the local
bundle exactly. HTTP calls use the actual read/report APIs and preserve returned
receipts. The local-function baseline and AgentTeams are different runtimes;
identical tool semantics alone do not eliminate this comparison confound.

The runner saves `run-record.json`, `protocol.json` and `model-trace.json` after
each stage. Traces retain requests, original provider response objects including
usage, assistant messages, tool arguments and results (apart from credential
redaction). They do not record authorization headers. Runtime claims remain
local observations, not independent attestation. Cost is `null` because provider
usage does not establish actual billed cost.

Token counts aggregate provider `prompt_tokens`/`completion_tokens` over every
request, including failed report-repair attempts. Input preflight uses a
conservative serialized UTF-8 byte bound, and `max_tokens` is capped at the
remaining output budget. This byte bound is not a model tokenizer guarantee;
reported overruns are recorded and stop the run. Missing usage stops further
requests instead of inventing zero cost. Tool attempts also consume the common
16-call budget; limits never reset each round. The runner caps iterations at 12,
responses at 1 MiB and submitted reports at 256 KiB. A transport failure, malformed
output or exhausted budget produces a genuine failed record; no fixture report
is substituted.

Only completed records can be passed to the evaluator with `--import-run`.
Review actual execution, semantic adequacy, trial counts and runtime differences
before making any claim about single-agent versus multi-agent effectiveness.

### Runtime integrity and repeated-attempt boundary

Before its first model request, the HTTP runner fetches the existing gateway run
metadata (the read-only reports endpoint; no tool quota is consumed). It verifies
the run hash, run ID, single-agent mode, evidence ID/hash, exact common budget and
tool scope. The gateway run must have no reports or consumed tool receipts. Each
subsequent read receipt is checked for its hash, run, evidence, role, sequence and
tool. A submit acknowledgement must contain the exact submitted report, expected
report ID, matching run/receipt hashes, valid citation status and
`actions_executed=false`; HTTP 200 alone is not acceptance.

Every local invocation first atomically claims its run ID in the current OS
user's `~/.local/state/cyberguard/model-attempts.sqlite`. Claims are kept after
failure or process death. Reusing a run ID is rejected even with another output
directory, so retries must receive new attempt/run IDs and keep prior costs in
the experiment accounting. The default random run ID makes this explicit without
resetting an earlier run's ledger. Tests may supply an isolated ledger path via
the Python API; the CLI does not expose this override.

The SQLite claim is atomic only for runners sharing that OS-user ledger. The
gateway metadata check is **not a distributed atomic claim**. Do not concurrently
use the same gateway run from another host, OS user or separate ledger. A trusted
operator can delete a ledger or choose a new run ID; this is local prototype
accounting, not an adversary-resistant global spending limit. Token totals from
all new attempts still belong in the overall experiment cost.

Strict JSON validation checks finite numbers throughout the whole tree,
including exponent overflow such as `1e999` and unknown fields. Reports reject
unknown top-level/nested contract fields in this runtime. An invalid provider
response cannot poison final JSON serialization and leave a run marked running.
Credential redaction traverses string values and keys before JSON encoding, so
quotes or backslashes in a credential cannot bypass redaction.

Atomic artifact writes retry transient `PermissionError` at most three times,
with 25/50 ms pauses, to tolerate brief Windows file locks. This retries only
file I/O, never model requests or tools. A persistent failure returns
`artifact_persistence_failed` and explicitly warns that the final record may not
have reached disk; it is never reported as a completed durable run.
