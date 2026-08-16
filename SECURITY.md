# Security policy

## Supported versions

CyberGuard is pre-1.0. Only the latest tagged release receives security fixes. AgentTeams compatibility is intentionally pinned; do not report an untested version bump as a CyberGuard vulnerability.

## Reporting a vulnerability

Use GitHub private vulnerability reporting or a private draft Security Advisory in the public repository. If private reporting is unavailable, open a minimal issue asking for a maintainer contact without including exploit details, credentials, customer telemetry or affected hostnames.

Include the affected version, component, reproduction preconditions, impact, and a safe proof of concept using the deterministic scenarios when possible. Expect an acknowledgement within three business days. Coordinated disclosure timing will be agreed after impact and remediation are confirmed.

Do not test against systems or data you do not own. Never place secrets, raw Matrix exports, production indicators, approval tokens or live connector responses in a public report.

## Security boundaries

The read-only gateway, response executor and AgentTeams control plane have different trust levels. A report that only demonstrates an Agent producing unsafe text is incomplete unless it also shows a policy or execution boundary can be crossed. Conversely, an approval bypass, credential exposure, audit-chain break, destination-control bypass or false verified recovery is security-significant even when the simulated action itself is harmless.
