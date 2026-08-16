# CyberGuard threat model

## Protected assets

- LLM, SIEM, EDR, firewall and threat-intelligence credentials.
- Restricted telemetry and collected evidence.
- Human approval authority.
- Integrity of incident decisions, action history and final reports.
- Availability of AgentTeams and monitored business systems.

## Trust boundaries

1. Human ↔ Matrix/Element: humans may approve, interrupt or correct tasks.
2. AgentTeams ↔ Workers: Worker output is untrusted until supported by evidence.
3. Higress ↔ MCP/API services: real credentials stay in the gateway.
4. Read-only investigation ↔ mutating response: separate services, tokens and Docker networks.
5. CyberGuard ↔ external security products: connector responses are untrusted data.
6. Container control plane ↔ host: Docker runtime access is equivalent to powerful host access.

## Primary threats and controls

| Threat | Control |
|---|---|
| Tool-output prompt injection | Skills instruct Agents to treat output as data; structured schemas; allowlisted tools |
| Hallucinated root cause | Competing hypotheses, evidence IDs, confidence and independent verification |
| Credential exfiltration | Higress broker; distinct tokens; secrets never placed in prompts or Matrix |
| Unauthorized response | Separate executor token plus human-only approval secret; expiring approval is cryptographically bound to one proposal record |
| Repeated action | Required idempotency key, serialized state transitions, exactly-once execution and permanently closed rollback state |
| Excessive blast radius | Small action allowlist, exact target, L0–L3 risk model and rollback |
| Audit tampering | SHA-256 chain plus HMAC-SHA256 per record; authenticated checkpoints can be retained outside the action volume |
| Cross-incident confusion | Mandatory incident ID in every tool call, evidence item and action |
| False recovery from an unrelated action | Scenario-declared action/target set matched against authenticated active executor state; partial, wrong-target and rolled-back sets fail closed |
| Boundary-source spoofing | Firewall/gateway source identity and handling label are server-owned; policy evidence is correlated with observed NDR traffic |
| Sensitive-data leakage | Handling labels; large/restricted data stored by reference |
| Supply-chain compromise | Pinned AgentTeams release and Python dependencies; restricted image registries |
| Container escape/host takeover | Non-root, read-only filesystems, no-new-privileges, dropped capabilities; dedicated host |

## Safety invariants

1. An L2 action cannot execute without a valid, unexpired human approval bound to the exact proposal hash.
2. The Agent never receives the human approval secret.
3. The planner and verifier are different Workers.
4. Every consequential claim cites an Evidence ID or Action ID.
5. Every executed action is allowlisted, scoped, idempotent and reversible in the competition demo.
6. Failure or uncertainty moves the incident backward to investigation or rollback, never silently to closed.
7. Recovery evidence is released only when the executor confirms the complete required action/target set over an authenticated read-only channel.

## Known limitations

- The starter uses deterministic simulation data; production connector authenticity is not yet cryptographically verified.
- HMAC-authenticated local audit logs detect data-volume rewrites, but production-grade non-repudiation still needs exported checkpoints in remote append-only storage or an asymmetric signature service.
- Agent-level adherence must be measured with adversarial evaluation; prompts alone are not a security boundary.
- Docker Socket/Proxy access remains sensitive and requires a dedicated server and restricted administrators.
