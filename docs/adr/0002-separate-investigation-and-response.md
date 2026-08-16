# ADR 0002: Separate investigation from response authority

- Status: accepted
- Date: 2026-08-13

## Context

Security telemetry and external tool output are attacker-influenced. Giving every investigating Agent mutating credentials would allow hallucination or prompt injection to become an operational incident.

## Decision

Run read-only investigation and response execution as separate services with distinct credentials. The response service accepts only allowlisted typed actions. Every action is proposed with an idempotency key, requires a human-controlled approval bound to the proposal hash, produces an HMAC-authenticated hash-linked audit event and has a rollback path. A separate Worker verifies recovery through an authenticated read-only state endpoint.

## Consequences

- Investigation Workers cannot directly alter infrastructure.
- Human approval remains meaningful because its secret is never assigned to an Agent.
- Additional vendor actions must be deliberately added to the allowlist and tests.
- The extra gate adds latency but materially reduces unsafe-action risk.
