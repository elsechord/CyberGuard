# Proposed QwenPaw startup readiness patch

Status: source patch and fake-client tests only. The image has not been built;
the running containers have not been patched or restarted by this change.

The Dockerfile pins the RepoDigest read from the actual `cg-inv005-planner`
base image on 2026-09-17. The strict replacement refuses source drift and
already-patched input. It changes only `Worker._wait_for_qwenpaw_api`.

The method requires `/api/version` and the read-only `/api/mcp` list to succeed
in the same attempt. It bounds the entire coroutine with `asyncio.timeout(120)`
and uses a 0.5-second delay after a failed probe. Existing per-request HTTP
timeouts are unchanged. No model, mutation, or tool-policy operation is retried.

Cancellation of `asyncio.to_thread` does not terminate an already-running
socket operation. That read-only operation may continue until the existing
client socket timeout; the readiness coroutine still ends at its deadline.
Client socket timeouts also do not guarantee a strict lifetime bound on every
possible blocking OS operation.

`list_mcp` success establishes management Workspace readiness, **not** successful
connection or permission for every MCP tool. Required tool availability and
policy must still be checked with the model guard disarmed. This patch does not
repair Higress routing, Driver connection failures, or runtime authorization.

Run fake tests from the repository root:

```sh
python -m unittest discover -s deploy/agentteams-local -p test_qwenpaw_readiness.py -v
```

Proposed build command, not executed by the patch author:

```sh
docker build -f deploy/agentteams-local/qwenpaw.Dockerfile -t cyberguard-qwenpaw:readiness-local .
```

Before deployment, inspect the build diff, retain the original image digest,
and test one fresh Worker with the guard disarmed. Export its startup logs and
management readiness timings. Passing fake tests is not proof of successful
real startup.
