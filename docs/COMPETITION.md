# Competition alignment and evidence plan

CyberGuard optimizes for the published Agent Infra scoring structure. A feature is not considered complete merely because it appears in a diagram; each claim needs a runnable artifact and evaluation evidence.

| Area | Weight | CyberGuard evidence | Remaining evidence before submission |
|---|---:|---|---|
| Agent design | 25% | Seven bounded roles; read/write separation; role-specific Skills and tool permissions | Export successful role behavior from both scenarios |
| Multi-Agent collaboration | 25% | Team Leader workflow, parallel specialists, evidence handoffs, planner/responder/verifier separation | Run single-Agent and collaboration ablations with fixed model/settings |
| Reusable Skills | 25% | Ten standalone Skill packages with input, policy, failure and output guidance, including boundary defense | Distribute ZIPs through AgentTeams v1.2.2 and capture hot-load evidence |
| Engineering completion | 20% | Docker deployment, schemas, health checks, tests, approval, rollback, audit verification and operations docs | Complete server Docker build and AgentTeams end-to-end smoke test |
| Open-source contribution | 5% | Apache-2.0 CyberGuard repository structure and upstream contribution plan | Publish repository; reproduce a current AgentTeams issue before proposing PR |

## Submission claims that require proof

1. “Multi-Agent improves quality” requires benchmark results, not a conversation screenshot.
2. “Safe autonomous response” requires a recorded refusal before approval, successful approved execution, rollback and audit verification.
3. “Resists prompt injection” requires the supply-chain scenario to complete without copying or following the injection marker.
4. “Evidence-driven” requires consequential report claims to cite valid Evidence IDs and independent sources.
5. “Reusable Skills” requires the same Skill packages to operate across both scenarios without scenario-specific prompt changes.
6. “Verified recovery” requires the exact approved action/target set declared by the scenario; an unrelated or partial response must remain inconclusive.
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
