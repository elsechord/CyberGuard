# Live connector configuration

[简体中文](LIVE_CONNECTORS.zh-CN.md) · [中文文档导航](README.zh-CN.md)

CyberGuard competition scenarios require no external security products. To use live telemetry, copy `config/connectors.json.example` to `config/connectors.json`, adapt only the server-owned paths, and populate the corresponding base URLs and tokens in `.env`. The example includes SIEM, NDR, firewall/gateway, EDR and CMDB adapters.

Agents call the same tools with `scenario_id: live`. They can provide query arguments but cannot supply the upstream URL, authentication header or credential. The gateway loads those values from its read-only configuration and environment.

Evidence `source` and `handling` are also server-owned. Any same-named fields returned by an upstream system are overwritten by the connector definition so a compromised source cannot inflate the independent-source count or downgrade classification.

## Normalized response

A connector may return the native vendor JSON. CyberGuard wraps it as restricted evidence. Prefer an adapter endpoint that returns:

```json
{
  "source": "wazuh-indexer",
  "kind": "alert_bundle",
  "summary": "Three correlated authentication alerts were found.",
  "data": {"alerts": []},
  "confidence": 0.86,
  "attack_techniques": ["T1078"],
  "supports": ["H1-credential-compromise"],
  "contradicts": [],
  "handling": "restricted",
  "observed_at": "2026-08-13T01:12:00Z"
}
```

The gateway adds the Evidence 1.0 standard metadata, stable entities/observables and a deterministic quality result. Live records below `CYBERGUARD_MIN_EVIDENCE_QUALITY` (default `0.7`) are rejected before they enter the incident ledger. See [the security observation model](OBSERVATION_MODEL.md).

All upstream strings remain untrusted data. Do not use an upstream-provided confidence score unless the adapter documents its semantics.

## Transport policy

- HTTPS is mandatory by default.
- `CYBERGUARD_ALLOW_INSECURE_HTTP=1` is only for a private lab network.
- Connector paths are fixed in the server configuration and may not contain `..`.
- Credentials in URLs are rejected.
- Upstream responses are limited to 2 MB and 30 seconds.
- GET connectors reject Agent arguments to avoid unsafe query-string construction; use a bounded POST adapter for searches.

## Vendor adapter pattern

For a vendor whose query schema differs, deploy a small adapter beside the gateway:

```text
CyberGuard Agent → fixed tool contract → adapter → vendor API
                                          │
                                          └─ normalizes timestamps, entities and handling labels
```

Keep adapter credentials in its own secret store or Higress. Add contract fixtures and tests before enabling a new source in a competition demonstration.
