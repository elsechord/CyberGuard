# Copy this request to Manager: default after the primary CyberGuard Team works

Create three additional benchmark Teams sequentially and idempotently. These Teams are experimental controls, not production teams. Keep the model provider, exact model ID, temperature, tool snapshots, scenario fixtures and timeout identical to `cyberguard-soc`. Do not reuse a Team Room between variants.

## 1. `cyberguard-single-agent`

Create one general security Worker named `benchmark-generalist`. Assign all ten CyberGuard Skills and both CyberGuard tool services. It alone performs intake, investigation, planning, response and verification. It must still obey the human approval secret boundary, but it has no specialist parallelism and no independent verifier.

## 2. `cyberguard-no-contract`

Create the same seven functional roles as `cyberguard-soc`, but use benchmark-only copies whose instructions explicitly prohibit Evidence IDs, the Incident/Evidence JSON schemas and structured evidence handoffs. They may collaborate in prose and retain the same read/write tool boundaries. Keep the independent verifier.

## 3. `cyberguard-no-verifier`

Create the same roles, Skills, evidence contract and tool boundaries as `cyberguard-soc`, except omit `recovery-verifier`. The controlled responder reports its own post-action outcome to the Team Leader. Human approval remains mandatory.

## Fixed experimental rules

- Do not silently restore any capability disabled by the variant.
- Do not change prompts after inspecting outputs from another variant.
- Do not discard failed runs or create replacement runs under the same run ID.
- Do not expose the approval secret to any Worker.
- Confirm the exact Matrix room ID for each Team, not only the display name.

Return a table containing Team name, room ID, Worker list, assigned Skills, tools and explicitly disabled capabilities. The existing `cyberguard-soc` room is the `cyberguard-full` variant. Copy all four room IDs into `benchmark/room-map.json` on the server.
