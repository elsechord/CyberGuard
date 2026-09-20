---
name: cyberguard-adaptive-collaboration
description: Decide whether a CyberGuard investigation Task needs temporary specialists, run them through native WorkerFlow, and retain evidence-linked collaboration records.
---

# Adaptive investigation collaboration

Use the smallest team that answers the evidence questions. A short, single-source
check normally needs no internal subagents. Split work when independent questions
can be investigated in parallel, or a different method can resolve a concrete
disagreement. Extra copies of the same reasoning are not independent evidence.

Keep TeamHarness responsible for Task assignment and acceptance. Use WorkerFlow
for temporary experts inside your assigned Task; they do not become team Workers.
The separate verification Worker still checks original evidence independently.

## Choose and explain the work

For each expert, specify a question, original `material_ids`, and its expected
result. Available templates: `source-reader`, `hypothesis-checker`, and
`timeline-correlator`. Roles can be reused with different concrete questions.
Use zero to three temporary experts by default, one level deep. These are local
capacity defaults, not a claim that three is optimal.

Put your plan in the existing Task directory. Use the installed
`/opt/cyberguard-collaboration/native_collaboration.py` helper for native lifecycle and
snapshot export; run its `--help` for exact arguments. It explicitly inherits
your active model, bounds the number of temporary agents, and calls WorkerFlow.
It does not replace the native scheduler or perform investigation itself.

## Communicate only when useful

Send each returned `submitPrompt` to its `agentId` with QwenPaw
`submit_to_agent`. Receive results with the runtime's task communication tools.
For a specific question, use `chat_with_agent` to the relevant peer or parent.
Give its exact agent ID, the question and relevant evidence references. Do not
send greetings, acknowledgement loops, or entire conversation histories.

Read the tool schema once if unsure. A temporary expert may ask its parent for
missing context or a peer for a specific fact. Make peer IDs and parent ID
available in the task message. Keep queries short; a reply is another agent's
interpretation until checked against the source. Record useful exchanges with
`record-message`; distinguish a recorded exchange from a verified transport receipt.

Use native `workflow_update` through the helper after results arrive; send any
newly returned `readyInstructions`. Do not mark a child done merely because it
was submitted. The helper exports a compact `collaboration.json` in the Task
directory, without full prompts or hidden reasoning.

## Finish and retain the result

Stop when the questions are answered, or explain the exact missing evidence.
Repeated uncertainty without new evidence calls for a material request, not
more agents. Preserve meaningful disagreements for the independent verifier.

Finish or fail the native workflow through the helper to release temporary
agents and retain shared artifacts. Add `collaboration.json` to the Task's
published deliverables. A project pause stops future dispatch; finish or fail
any already-running internal workflow before leaving the task.

For the final verifier Task, produce the exact report schema supplied by the
Leader. Cite original material text, not a peer's paraphrase. Use concise Chinese
when the investigation request is Chinese.
