# Security observation model

CyberGuard normalizes SIEM, threat-intelligence, NDR, EDR/runtime, CMDB and recovery records into one hash-bound `CyberGuard Evidence` contract before Agents can cite them. The native record remains in `data`; normalization adds correlation and quality metadata without rewriting the original observation.

## Compatibility posture

- `standard.alignment.event_profile` is **OCSF-aligned**, not a claim of formal OCSF conformance. CyberGuard uses vendor-neutral category/class/activity labels while preserving native fields.
- Network indicators use STIX 2.1 Cyber-observable vocabulary such as `ipv4-addr`, `ipv6-addr`, `domain-name` and `url`. The complete STIX specification remains authoritative: <https://docs.oasis-open.org/cti/stix/v2.1/stix-v2.1.html>.
- Adversary behavior is mapped only to syntactically valid MITRE ATT&CK technique/sub-technique IDs. ATT&CK Data Sources were deprecated in ATT&CK v18; future sensor coverage work should reference current Data Components instead of claiming deprecated Data Source coverage: <https://attack.mitre.org/datasources/>.

## Evidence 1.0 fields

| Field | Purpose |
|---|---|
| `sha256` | SHA-256 of the canonical native connector record |
| `standard.raw_sha256` | Binds normalized metadata back to the exact native record |
| `entities` | Stable, typed IDs for account, device, workload, service, namespace, image and process references |
| `observables` | Stable IDs plus STIX-compatible observable type and native value |
| `attack_techniques` | Valid ATT&CK technique/sub-technique IDs; invalid IDs are excluded and reported |
| `quality` | Deterministic score, pass/review gate, issues and required-field completeness |

Stable IDs are SHA-256-derived from normalized type and case-folded value. This makes `host=FIN-LT-023` from EDR and `src_host=fin-lt-023` from NDR converge without depending on a vendor field name. Raw values remain restricted evidence and must not be exported to a public dataset without redaction.

## Quality gate

The score is intentionally transparent:

- 50% required fields: source, kind, summary, object-valued data and bounded confidence;
- 15% valid observation timestamp;
- 15% at least one correlatable entity or observable;
- 10% at least one supporting or contradicting hypothesis;
- 10% at least one valid ATT&CK mapping.

Scores at or above `0.7` pass. Simulation fixtures retain review metadata for auditability; live connector records below `CYBERGUARD_MIN_EVIDENCE_QUALITY` are rejected before persistence. At incident level, `/incidents/{id}/quality` passes only when at least three independent sources exist and every retained record meets the 0.7 floor.

This gate measures evidence usability, not truth. Confidence still describes the adapter's assessed reliability, hypotheses can conflict, and the Agent workflow must request more evidence when the incident gate remains `review`.

## Correlation graph

`/incidents/{id}/graph` exposes source, evidence, entity, observable, ATT&CK technique, hypothesis, incident and response-action nodes. Shared stable IDs turn repeated mentions into explicit cross-source joins. The incident summary reports entity count, cross-source entity count, ATT&CK coverage, mean quality and review count so evaluators can distinguish actual fusion from parallel chat transcripts.

## Adapter acceptance checklist

1. Keep destination, path and credentials server-owned.
2. Keep evidence source identity and handling classification server-owned; never trust upstream overrides.
3. Emit an ISO 8601 `observed_at` time and document timezone handling.
4. Map at least one supported entity/observable field and preserve the native payload.
5. Link evidence to a bounded hypothesis and map only defensible ATT&CK techniques.
6. Add a fixture proving normalization, raw-hash binding, quality behavior and cross-source identity.
7. Test malformed time, invalid ATT&CK ID, oversized response and upstream failure paths.
