# Competition alignment and evidence plan

CyberGuard optimizes for the published Agent Infra scoring structure. A feature is not considered complete merely because it appears in a diagram; each claim needs a runnable artifact and evaluation evidence.

> **2026-09-03 update (v0.13.0)**: the previously missing pieces below are now closed. The live AgentTeams task run (CG-2026-0002, supply_chain_webshell) provides the native Matrix trace, human approvals, execution, two-round independent re-verification and rollback evidence; see the [v0.13.0 release](https://github.com/armaygooser/CyberGuard/releases/tag/v0.13.0) evidence archive and [docs/LIVE_TASK_EVIDENCE.md](LIVE_TASK_EVIDENCE.md). The 40-run ablation benchmark matrix remains the one optional open item.

| Area | Weight | CyberGuard evidence | Remaining evidence before submission |
|---|---:|---|---|
| Agent design | 25% | Seven bounded roles; read/write separation; role-specific Skills and tool permissions | ~~Export successful role behavior from both scenarios~~ ✅ v0.13.0 live run (webshell) |
| Multi-Agent collaboration | 25% | Team Leader workflow, parallel specialists, evidence handoffs, planner/responder/verifier separation | ✅ v0.13.0 native Matrix trace (2,992 events); ablation benchmark optional |
| Reusable Skills | 25% | Ten standalone Skill packages with input, policy, failure and output guidance, including boundary defense | ~~Distribute ZIPs through AgentTeams v1.2.2 and capture hot-load evidence~~ ✅ distributed at bootstrap, exercised in the live run |
| Engineering completion | 20% | Docker deployment, schemas, health checks, tests, approval, rollback, audit verification and operations docs | ✅ server acceptance + readiness gate `valid: true` |
| Open-source contribution | 5% | Apache-2.0 CyberGuard repository structure and upstream contribution plan | Publish repository; reproduce a current AgentTeams issue before proposing PR |

## Submission claims that require proof

1. “Multi-Agent improves quality” requires benchmark results, not a conversation screenshot.
2. “Safe autonomous response” requires a recorded refusal before approval, successful approved execution, rollback and audit verification. ✅ v0.13.0 evidence pack (`audit-verify-final.json`, `rollback-*.json`, `post-rollback-recovery.json`)
3. “Resists prompt injection” requires the supply-chain scenario to complete without copying or following the injection marker. ✅ two marker appearances ignored and reported in the live run
4. “Evidence-driven” requires consequential report claims to cite valid Evidence IDs and independent sources. ✅ `evidence-index.json` + validated references in the live run
5. “Reusable Skills” requires the same Skill packages to operate across both scenarios without scenario-specific prompt changes. ✅ same ten packages drove the deterministic two-scenario demo and the live webshell run
6. “Verified recovery” requires the exact approved action/target set declared by the scenario; an unrelated or partial response must remain inconclusive. ✅ demonstrated twice: wrong-target response stayed inconclusive until the exact contract action executed
7. “Production extensible” requires a live connector test where the Agent cannot choose the upstream destination or access its credential.

The server-side `tests/e2e_demo.sh` produces machine-verifiable evidence for claim 2 and for cross-service state propagation. It complements, but does not replace, the AgentTeams Matrix trace required to prove Agent collaboration.

## Demo sequence

1. Show the AgentTeams Team, assigned Skills and least-privilege tool access.
2. Submit the credential-compromise incident using only symptoms and initial alerts.
3. Show parallel investigations and evidence-indexed handoffs.
4. Demonstrate that execution is rejected before human approval.
5. Approve the exact Action ID outside the Agent, execute, independently verify and show rollback.
6. Run the supply-chain scenario and highlight the ignored malicious tool text.
7. Show the benchmark comparison and exported audit chain.

## Honest limitations

The competition package starts in deterministic simulation mode. Live connector contracts and server-owned secrets are implemented, but vendor-specific field mappings require the selected SIEM/EDR/NDR APIs. The response executor does not mutate real infrastructure until a dedicated connector and safety review are added.

The timed judge-facing sequence and its evidence checklist are maintained in [JUDGE_DEMO.md](JUDGE_DEMO.md).
