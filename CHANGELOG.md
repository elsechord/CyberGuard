# Changelog

## 0.15.0 — 2026-09-20

- Added native AgentTeams investigation delivery: Skill/Console intake, original evidence packets, Project/Task planning, independent verification and cited report retrieval.
- Added portable investigation Skill v0.2.0 and console-generated connection instructions for existing Agents.
- Preserved two consecutive full-case runs with original source materials, native workflows, report reviews and actual model usage under `docs/validation/full-case`.
- Added prepared task rooms and documented local v1.2.3 compatibility fixes for Worker addressing and model routing after restart.
- Completed a live two-round response chain: fresh observations → native investigation → bounded model proposal → approval → real execution → failed verification → re-investigation → new approved action → verified recovery. All 20 checks passed in 677.60 seconds in the benign process laboratory.
- Added clean-directory installation checks, fresh-volume Console onboarding, public collaboration evidence, an updated demo and exact-commit release packaging.

- Added the multi-user operations console (`services/operations-console`): a FastAPI control plane on internal port 8080 (host `127.0.0.1:18120`) that turns the single-token demo surface into a deployable product. It ships PBKDF2 password authentication with per-account exponential backoff and lockout, hashed session IDs in a `__Host-` cookie with idle/absolute expiry and rotation, a four-role RBAC matrix (viewer/analyst/approver/admin) enforced deny-by-default, scope-tagged `cg_live_` API keys with one-time plaintext display, an append-only `auth_event` audit trail with CSV export, and one-time first-boot `/setup` gated by a token printed to the container log (plus a `python -m app.bootstrap admin` CLI).
- Added console API v1 with dual session/API-key authentication, a unified envelope (`data`/`has_more`/`next_cursor`) and error shape, `Idempotency-Key` replay protection (24 h), and proxies onto the existing gateway incident/workflow APIs, the executor approval API (decisions require a mandatory closing classification and comment) and the optional model-guard admission ledger. Pages cover overview metrics, incident queue/detail with timeline, approvals, budget ledger, audit and admin settings; CSRF uses per-session synchronizer tokens plus Origin/`X-Requested-With` checks, behind a strict CSP. Documentation in `docs/OPERATIONS_CONSOLE.md`; tests in `tests/test_operations_console.py`.

## 0.14.0 — 2026-09-18

- Released the finals engineering layer (`2417da4`): the model admission guard as a service (durable run/role budgets, exact-request deduplication, restart disarming, closed ledgers), the isolated host-lab and identity labs (real `/proc` observation, version-bound persistence cleanup, receipt-bound approval/audit reconciliation), the bounded investigation pipeline with immutable run APIs, checksummed exports and a shared evaluation protocol, the Compose surface, and expanded documentation and tests.
- Normalized `LICENSE` to the canonical Apache-2.0 text and moved copyright attribution to a new `NOTICE` file so license detection is reliable (`b60218e`).
- Migrated the repository to the `elsechord` organization at `https://github.com/elsechord/CyberGuard`; the legacy remote stays read-only and is never pushed.
- Packaged the 2026-09-17 validation evidence as `validation-20260917T180221Z.tar.gz` and attached it to this release: host-lab validation (3 runs, including a rejection that prevented dispatch and supervisor-real restarts with version-bound persistence cleanup), a model-guard closed ledger (0 requests, 0 consumption), investigation bundles that passed the full chain, and local AgentTeams native attempt records.

### Details of the finals engineering layer

- Added an exercise-only model tool loop with retained provider usage, failed attempts, validated gateway acknowledgements, local attempt uniqueness and credential-redacted artifacts; direct model execution is explicitly separate from AgentTeams.
- Added pinned local AgentTeams Docker deployment and a documented upstream controller patch for localhost Worker consoles, narrow investigation MCP registration and native deployment snapshots.
- Added experimental pre-dispatch model admission with durable run/role budgets, exact-request deduplication, single-call concurrency, conservative unknown-usage reservations, restart disarming, and a fresh-Worker serial integration harness. Input reservation remains a tokenizer heuristic, not a guaranteed billing cap.
- Added bounded Linux evidence bundles, fixed-workflow cited investigation reports, separate exercise answer keys and a shared evaluation protocol; absent model executions remain `not_run`.
- Added immutable investigation-run APIs with separate intake/read/report credentials, persisted tool quotas, cross-run receipt validation and checksummed HTTP workflow exports.
- Added three-role AgentTeams investigation configuration, task-package generation and source-mapped runtime evidence checks. These prepare integration; structural validation does not attest an actual model or AgentTeams run.
- Added an isolated Linux process lab: real `/proc` observations, benign workload recurrence after process termination, version-bound persistence cleanup, pidfd targeting, and bounded independent verification with a progressing control workload.
- Reuse proposal-bound approval and audit reconciliation for `host_lab`; stale objects are rejected, irreversible process actions cannot claim rollback, and a later run cannot make an earlier action appear verified.
- Added explicit scripted/interactive approval modes, same-run failure and recovery exports, and negative tests for stale targets, missing telemetry, control failure, lost receipts and environment changes. This is not an AgentTeams/model execution or a real intrusion dataset.

- Added run-scoped tool evidence with envelope hashes, authenticated executor snapshots and checksummed JSON exports. Invalid audit/evidence cannot reuse an older successful observation; rollback invalidates the current action verdict without erasing historical observations.
- Added console run selection, mode and probe details, export download and explicit unverified AgentTeams/Skill provenance labels.
- Added a standalone non-root, offline Docker laboratory, hash-locked Linux builds and CI evidence upload/fault tests. It does not deploy AgentTeams or switch the production Compose configuration to lab mode.

- Added an opt-in loopback identity lab with real account disable/restore, SQLite-atomic operation receipts, run/environment binding and read-only access probes using separate account credentials.
- Persist dispatch intent before lab mutations. Lost or invalid receipts produce an unknown outcome; restart reconciliation reads receipts without blindly retrying a mutation. Rollback also requires the approval credential.
- Reject mutations when the audit chain is invalid. Require one executor process; no distributed exactly-once guarantee is claimed.
- Label fixture recovery as simulated; generic live connectors cannot establish verified recovery without a validated verifier contract. The dedicated lab verifier checks current target and control account access.
- Added a deterministic lab harness and checksummed evidence export, plus real HTTP tests for receipt loss, restart, audit corruption, stale state, wrong credentials, missing telemetry and simulation/lab separation.
- Fixed local test failure propagation and added hash-locked HTTP test dependencies to CI. Secret-file creation explicitly requires POSIX mode guarantees and uses non-overwriting atomic publication.
- Pinned Shell script line endings to LF so Windows checkouts can be validated and run by Bash/WSL.

## 0.13.0 — 2026-09-03

- Completed the judge-requested live evidence: one real AgentTeams task (CG-2026-0002, supply_chain_webshell) ran from creation to terminal state on AgentTeams v1.2.2 with the cyberguard-soc team — 2,992 native Matrix events, four hash-bound human-approved actions, two-round independent re-verification (inconclusive → verified) and a rollback that correctly reverted the verdict to inconclusive.
- Packaged the run as a checksummed evidence archive (event chains, approvals, executions, re-verification, rollback, terminal state, readiness gate) attached to this release.
- Added `scripts/capture-agentteams-task.py` (native Matrix event-chain capturer with approval-gate detection) and `docs/LIVE_TASK_EVIDENCE.md` (proven v1.2.2 registration path, including Higress single-label DNS, :443 port default and worker- consumer-name gotchas).
- Added `docs/SEMIFINAL_PLAN.md` with the 9.4 defense schedule and 2026-09-01 rule updates.

## 0.12.0 — 2026-08-16

- Added competition-ready Agent Identity and Skill inventories aligned with the August 15 Track 1 guide.
- Added fail-fast LLM provider preflight checks and verified the official DeepSeek route through the deployed Worker gateway without exposing credentials.
- Hardened AgentTeams acceptance so Worker Skill and MCP bindings are read from the actual Worker resources rather than trusted Manager claims.
- Upgraded all ten reusable security Skills to explicit input, dependency, execution, safety, failure and quality-gate contracts.
- Verified the remote two-scenario judge demo with twelve safety/lifecycle proofs and six exact response actions, plus 83 local automated tests.
- Refreshed the preliminary-round deck and release bundle with current deployment evidence and submission-ready materials.

## 0.11.0 — 2026-08-13

- Added a runnable `boundary.policy` investigation tool, firewall/gateway live-connector contract and boundary-policy evidence to both competition scenarios.
- Added the tenth reusable Skill, `boundary-defense`, and assigned it to the least-privilege `network-hunter` AgentTeams Worker.
- Added the reversible `quarantine_workload` action and expanded each deterministic scenario to an exact three-action credential/compute/boundary response contract.
- Bound recovery verification to the complete authenticated action-and-target set; unrelated, partial, wrong-target and rolled-back responses now remain inconclusive.
- Prevented the incident summary from reporting `verified` unless the latest recovery evidence explicitly has `verdict=verified`.
- Added benchmark ground truth v2 and structural checks binding actions to targets and verification to the exact Action ID set while preserving frozen v1.
- Added seven boundary, response-contract, benchmark and packaging contracts (72 automated tests total).

## 0.10.0 — 2026-08-13

- Added the hash-bound Evidence 1.0 normalization layer across SIEM, threat-intelligence, NDR, EDR/runtime, CMDB and recovery sources.
- Added OCSF-aligned event classes, STIX 2.1 observable types and validated MITRE ATT&CK technique/sub-technique mappings without claiming formal standard conformance.
- Added deterministic evidence quality scoring, a configurable live-ingestion floor and an incident-level three-source quality gate.
- Made live evidence source identity and handling classification server-owned to prevent provenance spoofing and classification downgrades.
- Added stable cross-vendor entity/observable IDs and expanded the explainable incident graph with entity, observable and ATT&CK nodes.
- Added quality and cross-source correlation summaries to the read-only audit console and API.
- Added seven normalization, rejection, correlation and configuration contracts (65 automated tests total).

## 0.9.0 — 2026-08-13

- Added a Matrix-native, hash-bound and idempotent AgentTeams v1.2.2 Manager bootstrap client.
- Added checksum-verified Skill staging through the configured AgentTeams `/host-share` contract.
- Added strict validation of the seven Worker roles, Skill assignments, tool least privilege and exact Team room ID.
- Added cross-checks against live AgentTeams Worker/Team CR snapshots and a checksummed competition-readiness report.
- Kept all bearer, approval and audit secrets out of Matrix while reducing baseline setup to one direct credential-broker registration plus one bootstrap command.
- Added a nested hash manifest that binds the Matrix request to every staged Skill and role specification.
- Added six AgentTeams bootstrap and readiness contracts (58 automated tests total).

## 0.8.0 — 2026-08-13

- Added HMAC-SHA256 authentication to every response audit record and exportable audit checkpoints.
- Bound human approvals to exact proposal hashes and execution records to exact approval hashes.
- Serialized proposal, approval, execution and rollback transitions for exactly-once behavior under concurrency.
- Added safe approval renewal after expiry and permanently closed actions after rollback.
- Replaced recovery's blind audit-file trust with an authenticated executor state query using a read-only credential.
- Split five deployment secrets by role and added six tampering, concurrency, recovery and deployment contracts (52 automated tests total).

## 0.7.0 — 2026-08-13

- Added two-scenario judge demo automation with machine-readable results and checksums.
- Added fail-closed benchmark provenance binding and a full 40-run matrix auditor.
- Added Wilson completion intervals, deterministic bootstrap metric intervals, pooled rates and missing-observation disclosure.
- Prevented failed runs from being misreported as zero-cost or zero-risk observations.
- Added server-acceptance failure forensics, image identity capture and a machine-readable acceptance manifest.
- Added eight evaluation, provenance and demonstration contracts (46 automated tests total).

## 0.6.0 — 2026-08-13

- Added hash-locked CPython 3.12/Linux x86_64 dependencies and digest-pinned container builds.
- Added least-privilege, SHA-pinned GitHub Actions CI with source and image vulnerability scans.
- Added deterministic SPDX source SBOM generation plus container SBOM publication.
- Added Dependabot, contribution, security-disclosure and reproducible-release guidance.
- Added ten supply-chain, SBOM and architecture contracts (38 automated tests total).

## 0.5.0 — 2026-08-13

- Added fail-closed validation for CyberGuard and AgentTeams deployment configuration without logging secret values.
- Added atomic mode-0600 secret generation and a single server bootstrap entry point.
- Added Linux host/resource/Docker preflight checks and integrated them into server acceptance.
- Added eleven deployment configuration, secret-generation and release-contract tests (28 automated tests total).
- Excluded private Matrix results, room maps and acceptance evidence from public release archives.

## 0.4.0 — 2026-08-13

- Added a Matrix-native AgentTeams benchmark runner for four fixed ablation rooms, raw trace retention and strict structured-report extraction.
- Separated Agent output collection from independent human ground-truth annotation and required real telemetry before successful runs can be aggregated.
- Added one-command server acceptance with timestamped evidence, redacted logs, image/OpenAPI provenance and SHA256 manifests.
- Pinned the AgentTeams v1.2.2 installer to its full release commit and verified installer SHA256 before execution.
- Added benchmark Team bootstrap instructions, judge demo runbook and three new benchmark integrity tests.

## 0.3.1 — 2026-08-13

- Added a cross-service server acceptance test covering investigation, pre-action verification refusal, approval enforcement, execution, recovery verification, audit integrity and rollback observation.
- Made the full E2E safety gate part of the default Docker deployment flow.

## 0.3.0 — 2026-08-13

- Added authenticated incident index, detail and evidence-graph APIs.
- Added a responsive, read-only evidence audit console with strict CSP and no third-party assets.
- Added incident status derivation from evidence and approval/action audit state.
- Added console/API regression coverage and server verification checks.

## 0.2.0 — 2026-08-13

- Added a supply-chain/WebShell scenario with adversarial tool-output prompt injection.
- Added server-controlled live connector contracts for SIEM, NDR, EDR and CMDB APIs.
- Added single-Agent, no-contract, no-verifier and full-CyberGuard ablation definitions and result aggregation.
- Pinned the Python base image and updated FastAPI, Uvicorn and Pydantic to current stable releases.
- Hardened response idempotency against key rebinding and documented competition evidence requirements and architecture decisions.

## 0.1.0 — 2026-08-13

- Added a Docker-deployable CyberGuard application layer for AgentTeams v1.2.2.
- Added evidence-driven read-only investigation tools and a deterministic credential-compromise scenario.
- Added approval-gated, idempotent and reversible response execution with hash-linked audit verification.
- Added seven Agent definitions, reusable security Skills, incident/evidence contracts and a structural evaluator.
- Added server installation, verification, operations and threat-model documentation.
