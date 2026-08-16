# ADR 0001: Build CyberGuard as an AgentTeams application layer

- Status: accepted
- Date: 2026-08-13

## Context

The track mandates AgentTeams and rewards Agent, collaboration and Skill quality. Reimplementing orchestration, Matrix communication, shared storage or credential brokering would consume effort without improving the security-domain result.

## Decision

Use AgentTeams v1.2.2 unchanged for Manager/Worker lifecycle, Team coordination, Matrix, Higress, MinIO and Skill distribution. CyberGuard owns security roles, evidence/action contracts, MCP/API tools, safety policy, scenarios and evaluation.

## Consequences

- AgentTeams can be upgraded independently after regression testing.
- CyberGuard remains an upstream application rather than a hard fork.
- Generic AgentTeams improvements can be submitted as small upstream PRs.
- The competition demo must visibly exercise AgentTeams-native Teams and Skills rather than hiding them behind a separate orchestrator.

