# Real-source ingest: Suricata EVE (read-only)

`scripts/ingest-suricata.py` is the first **real-source adapter**: it feeds
actual IDS logs into the same evidence pipeline used by simulated scenarios.
Suricata EVE JSON export files are converted to Evidence 1.0 records through
the gateway normalization module (stable entity/observable IDs, STIX typing,
ATT&CK validation, quality scoring), validated against
`contracts/evidence.schema.json`, and appended to the incident ledger
(`evidence.jsonl`) that the gateway console reads.

## What it is

- Read-only, offline ingestion: point it at an EVE JSON / JSONL export from
  your Suricata deployment and an incident id.
- Real data passes through the same quality gate and shows up in the same
  console (`/console`, `/incidents`, evidence graph) as scenario fixtures.
- Append-only: existing `evidence.jsonl` lines are never modified; re-running
  the adapter skips events whose content sha256 is already present
  (idempotent).
- Alert events (`event_type: alert`, including embedded `http`/`dns`/`tls`
  context) are converted. `stats` records and non-alert summaries are skipped
  by default; `--include-flows` also converts `flow` records.
- ATT&CK techniques are inferred only from a small, documented keyword table
  (see `ATTACK_HINTS` in the script). When no mapping is defensible the
  technique list stays empty and the record carries the `no_attack_mapping`
  quality issue — mappings are never invented.
- Suricata severity maps to confidence as 1 -> 0.9, 2 -> 0.75, 3 -> 0.6,
  unknown -> 0.5.

## What it is not

- It does not modify the Evidence 1.0 contract, the gateway service code, or
  any existing evidence record.
- It is not a live SIEM/EDR connector (see [LIVE_CONNECTORS.md](LIVE_CONNECTORS.md)
  for the server-owned live connector path). It reads files you already have.
- It does not normalize away unknown signatures: unmatched events keep their
  original signature/category text and an honest quality score.

## Usage

```bash
# Validate only (no writes)
python scripts/ingest-suricata.py \
  --input /var/log/suricata/eve.json --incident CG-SURICATA-001 \
  --data-dir ./data --dry-run

# Ingest alerts plus flow summaries, and open the incident workflow
python scripts/ingest-suricata.py \
  --input /var/log/suricata/eve.json --incident CG-SURICATA-001 \
  --data-dir ./data --include-flows --workflow
```

Parameters: `--input` (file or directory of `*.json`/`*.jsonl`, repeatable),
`--incident` (id, e.g. `CG-SURICATA-001`), `--data-dir` (gateway data dir),
`--dry-run`, `--include-flows`, `--workflow` (records a `received` ->
`investigating` transition for session `ingest-suricata`), `--sensor`
(reporting device entity, default `suricata-sensor`), `--environment`
(`live` for real sensor exports, `fixture` for spec samples such as
`samples/suricata/eve-sample.jsonl`).

The script prints a JSON summary: lines read, converted/skipped breakdown,
quality-score distribution, entity/observable counts and mapped techniques.

## Demo flow

```bash
# 1. Ingest the bundled sample (marked as fixture provenance)
python scripts/ingest-suricata.py \
  --input samples/suricata/eve-sample.jsonl --incident CG-SURICATA-001 \
  --data-dir ./data --environment fixture --workflow

# 2. Start the gateway on that data dir
CYBERGUARD_API_TOKEN=dev-token CYBERGUARD_SCENARIO_DIR=./scenarios \
CYBERGUARD_DATA_DIR=./data CYBERGUARD_ACTION_AUDIT_FILE=./data/actions.jsonl \
uvicorn app.main:app --app-dir services/security-tool-gateway --host 127.0.0.1 --port 18100

# 3. Watch real IDS events flow through the console
curl -H "Authorization: Bearer dev-token" http://127.0.0.1:18100/incidents
open http://127.0.0.1:18100/console   # incident CG-SURICATA-001, live evidence stream
```

The sample file mixes verbatim example records from the official Suricata user
guide with records synthesized per the public EVE schema; its provenance table
is documented in `samples/suricata/README.md`. Do not present it as a capture
of a specific real intrusion.

## Boundary and roadmap

Suricata EVE is the **first real-source adapter** and defines the pattern for
file-based ingest: reuse normalization, validate against the contract, append
only, stay idempotent. Commercial SIEM/EDR source connectors (live, server-
owned credentials) remain on the roadmap; see [LIVE_CONNECTORS.md](LIVE_CONNECTORS.md)
for the existing live-connector mechanism they will build on.
