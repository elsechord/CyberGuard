# Suricata EVE sample (`eve-sample.jsonl`)

JSONL cannot carry comments, so provenance for each line is documented here.

This file is a demo/test fixture for `scripts/ingest-suricata.py`. It mixes two
kinds of content and **must not be presented as a capture of one specific real
intrusion**:

| Line | Event type | Origin |
| ---- | ---------- | ------ |
| 1 | alert (with http/fileinfo/flow context) | Verbatim example record published in the official Suricata user guide, `doc/userguide/output/eve/eve-json-format.rst` (OISF/suricata `main`). The guide notes the examples come from a public any.run task pcap. |
| 2 | alert | Verbatim example record from the same official guide (section "Eve JSON Format", the 2017-04-07 dotted-quad POST example). |
| 3 | http | Verbatim example record from the same official guide (full-record HTTP example with request/response headers). |
| 4 | flow | Verbatim example record from the same official guide (full-record flow example with tcp section). |
| 5 | anomaly | Verbatim example record from the same official guide (full-record anomaly example). |
| 6 | stats | Synthesized per Suricata EVE schema (public spec, `doc/userguide/output/eve/`): counters section per the stats output documentation. |
| 7-8 | dns request/response | Synthesized per Suricata EVE schema v15 (public spec); field names and shapes follow the DNS logging section of the official guide. |
| 9 | tls | Synthesized per Suricata EVE schema v15 (public spec); field values follow the "extended TLS logging" example shape from the official guide with `example.com` values. |
| 10-12 | alert (dns / tls / scan contexts) | Synthesized per Suricata EVE schema v15 (public spec), field values referencing the public examples above; signature texts are generic descriptors of common ET-style rule families, not claims about specific real rules or a specific real attack. |

Sources of record (public):

- Suricata user guide, EVE JSON format:
  https://docs.suricata.io/en/suricata-latest/output/eve/eve-json-format.html
  (file: https://github.com/OISF/suricata/blob/main/doc/userguide/output/eve/eve-json-format.rst)
- Suricata EVE output configuration (stats): `doc/userguide/output/eve/eve-json-output.rst`

Use `--environment fixture` when ingesting this file so the resulting evidence
records are marked `environment=fixture / execution=simulated` instead of
`live/real` sensor observations.
