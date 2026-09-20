# Investigation request

The JSON object contains `title`, `objective`, `domain` and a nonempty `materials`
array. Domain is `security`, `finance`, `legal` or `general`.

Each material has textual `name` and `content`, a `source_type` from `agent`,
`firewall`, `edr`, `honeypot`, `server_log`, `financial_record`, `audit_report`,
`judicial_document`, `other`; and `media_type` from `text/plain`,
`application/json`, `text/markdown`, `text/csv`. JSON content is a JSON-encoded
string. Optional `source_uri`, `interpretation`, and `observed_at` are strings.
Use ISO 8601 timestamps when known. Do not invent timestamps or source identities.

Supply original observations in `content`; put prior conclusions or hypotheses
in `interpretation`. Mark simulated content clearly in its name and content.
Binary/PDF inputs require a separately authorized extraction step; preserve the
original reference and label extracted text. The helper never fetches URLs.

Submission sends an `Idempotency-Key` header and expects `{data: {id, status,
links, ...}}`. Receipt files retain the key and input digest for recovery.
Status files contain the returned task; result files contain `investigation_id`
and `report` only when status is `completed` and a report is present. Keep
receipts and reports private under the destination directory's access controls.
