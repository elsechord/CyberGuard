# Read-only Linux evidence bundles

[简体中文](EVIDENCE_BUNDLES.zh-CN.md) · [中文文档导航](README.zh-CN.md)

This collector creates investigation inputs, not a security verdict. It does not execute
commands found in files, run a shell, collect process environments or command-line arguments,
change host configuration, or connect to external services. It uses only Python's standard library.

## Collect

Run on the Linux system or container to be investigated, under the account whose access scope
you want recorded. The default collects the visible process namespace and the collector's TCP/UDP
network namespace. It does **not** recursively scan logs, home directories, credentials, or `/etc`.

```sh
python scripts/collect-linux-evidence.py --output /tmp/cyberguard-evidence.json

# Explicit additional sources; paths are examples, not mandatory host files.
python scripts/collect-linux-evidence.py \
  --config /etc/systemd/system/example.service \
  --config /etc/cron.d/example \
  --log /var/log/auth.log \
  --sample-seconds 0.5 \
  --output /tmp/cyberguard-evidence-with-logs.json
```

Output files are never overwritten. They may contain hostnames, user identifiers, IP addresses and
operational details. Log content is explicitly opt-in and credential redaction is best effort;
review or pre-sanitize logs before sharing with other teams or model providers. Known token/password
assignments, HTTP credentials and authorization values are redacted. Files containing recognizable
private-key material are omitted as text. This is not a general data-loss prevention system.

For isolated tests, `--proc-root /path/to/proc-fixture` reads only that selected process tree and
labels the provenance `exercise`. It does not label individual processes benign or malicious.
No CPU-load or mining workload is started by collection.

## Data contract

Envelope schema: `cyberguard-evidence-bundle/v1`.

| Field | Meaning |
|---|---|
| `bundle_id`, `created_at` | Unique ID and timezone-qualified creation timestamp |
| `provenance.kind` | `live_collection`, `exercise`, or `import`; producer-supplied, not authenticated |
| `artifacts` | Individually hashed evidence records |
| `bundle_sha256` | SHA256 of the envelope with this field removed |

Every artifact contains exactly `evidence_id`, `kind`, `source` (string), `collected_at`,
`observed_at`, `status` (`collected` or `unavailable`), `data` (object), and `sha256`.
Artifact hashes remove only the artifact's own `sha256` field. Both hashes use UTF-8 JSON with
`sort_keys=True, ensure_ascii=False, separators=(',', ':')` and finite numbers only.
Bundle hashing includes artifact hashes. Hashes detect changes relative to a recorded digest;
they do **not** authenticate a collector, prove that a host is uncompromised, or establish that
producer-provided facts are true. Preserve the original bundle when importing it elsewhere.

Collector artifact kinds:

| Kind | `data` and scope |
|---|---|
| `processes` | `processes`: PID, PPID, real UID if available, `comm`, executable link if available, `starttime_ticks`, CPU observation. Identity must match across both samples. No `cmdline` or `environ`. |
| `network` | One artifact per `/proc/net/{tcp,tcp6,udp,udp6}`; `connections` with endpoints, hex kernel state, inode, best-effort `owner_pids`. Empty ownership is unknown, not absence of a process. |
| `persistence` | One per selected file; `entries` for systemd ExecStart/Pre/Post executable tokens or cron executable tokens. Arguments are omitted. `enabled:null`: a file's existence does not prove enablement. |
| `auth_logs` | One per selected log; `events` containing one-based line number and redacted text. No inferred actor, ingress route, or attribution. |

Every kind includes `coverage`. Source failures include `reason`; unavailable sources are not
silently converted to empty success. An empty collected file or socket table proves only that
the selected read returned no entries at that time. It does not prove the system is clean.
Unrequested logs and persistence sources appear as `unavailable/not_requested`.

Process CPU is a short-window estimate of core utilization, not proof of mining. Collection is
not atomic, processes may disappear, and PID namespaces, hidepid, privileges and network namespaces
limit visibility. Socket owners may race process exit or descriptor reuse. There is no eBPF,
container-host escape, history reconstruction, binary malware classifier, or organization attribution.
Systemd expansion, shell wrappers, cron environment semantics and activation are not resolved;
the parser exposes a limited correlation input, not the effective service configuration.

## Import/API

```python
from cyberguard_investigation.evidence import make_artifact, make_bundle, load_bundle, validate_bundle
from cyberguard_investigation.collector import collect_linux

bundle = load_bundle("/tmp/cyberguard-evidence.json")
validate_bundle(bundle)  # returns bundle; raises ValueError on invalid structure/integrity
```

`make_artifact(kind, source, data, *, status='collected', observed_at=None, collected_at=None)`
and `make_bundle(artifacts, *, provenance, bundle_id=None)` create envelopes. A caller can supply
other documented artifact kinds; the envelope validator validates JSON shape/integrity rather
than treating arbitrary application data as verified semantics.

Import limits: 8 MiB input/canonical bundle, 2,048 artifacts, 256 KiB canonical artifact,
depth 32, 100,000 visited JSON values, no duplicate object keys or duplicate evidence IDs.
NaN/infinity, malformed timestamps, unsupported fields and digest mismatches are rejected.
Readers must keep these limits when exposing HTTP import; accepting a JSON upload is not
authorization to execute any file content or any proposal described by that upload.

Collection limits: 512 processes, 256 descriptors per observed process, 512 sockets per table,
64 KiB per socket table, 32 explicitly selected files, 64 KiB per file, 1,024 log lines per file,
and 0.01–2 seconds of requested CPU observation. Truncation is recorded in coverage.
Explicit file reads reject final-component symlinks and non-regular files; callers should select
trusted directory roots. Collection of a changed live file is not a transactional filesystem snapshot.

## Verify

```sh
python tests/test_investigation_evidence.py
```

Tests cover tampering even with a recomputed outer hash, duplicate IDs and JSON keys, import bounds,
non-finite/deep structures, unavailable sources, PID reuse, CPU/parent/UID extraction, socket decoding,
secret-bearing argument omission, log redaction/truncation, and refusal to read non-regular files.
