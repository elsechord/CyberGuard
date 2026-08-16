# CyberGuard v1.2.2 idempotent bootstrap request

Execute this request sequentially. Do not recreate resources that already match; report drift instead of silently duplicating them.

1. Verify that the Manager can discover `cyberguard-readonly` and `cyberguard-response`. Never request, print or copy their bearer credentials. Stop with `status=needs_human_tool_registration` if either service is absent.
2. Hash `/host-share/cyberguard-bootstrap/BOOTSTRAP-SHA256SUMS` and require it to equal the `CYBERGUARD_BOOTSTRAP_BUNDLE_SHA256` value in this Matrix message. Then verify every entry in that manifest, import the ten ZIP packages under `/host-share/cyberguard-bootstrap/skills/`, and also verify their package-level `SHA256SUMS` before distribution. Stop if any verification fails.
3. Apply the seven Workers and `cyberguard-soc` Team exactly as specified in `/host-share/cyberguard-bootstrap/create-team-message.md`. Preserve tool least privilege: all investigation roles and the Team Leader receive `cyberguard-readonly`; only `controlled-responder` and the Team Leader may access `cyberguard-response`.
4. Verify every Worker is ready, every Skill assignment matches, and the Team room contains the expected roles. Do not send a demo incident during bootstrap.
5. Enforce the Simplified-Chinese language policy in `create-team-message.md` for every Worker and the Team Leader. Keep only protocol identifiers, evidence IDs, IOC values, ATT&CK IDs, commands, API paths and JSON field names in their original form.
6. Write `/host-share/cyberguard-bootstrap/manager-result.json` using this schema:

```json
{
  "schema_version": 1,
  "status": "complete",
  "team": {"name": "cyberguard-soc", "room_id": "!exact:matrix-domain"},
  "workers": [
    {"name": "alert-fusion", "ready": true, "skills": ["alert-triage", "hypothesis-testing"], "tools": ["cyberguard-readonly"]}
  ],
  "tool_services": ["cyberguard-readonly", "cyberguard-response"],
  "approval_secret_exposed": false,
  "notes": []
}
```

Include all seven Workers. Use exact resource and Skill names, not prose aliases. After the file is durably written, reply once with the literal marker `CYBERGUARD_BOOTSTRAP_COMPLETE` followed by a concise status table. If any invariant cannot be proven, do not emit the completion marker.
