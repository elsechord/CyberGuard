#!/usr/bin/env python3
"""Apply one exact, fail-closed readiness replacement to the pinned Worker source."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


ORIGINAL = '''    async def _wait_for_qwenpaw_api(self) -> None:
        deadline = time.monotonic() + 60
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            if self._process is not None and self._process.returncode is not None:
                raise RuntimeError(
                    f"qwenpaw app exited before API readiness: {self._process.returncode}",
                )
            try:
                await asyncio.to_thread(self.api_client.require_version, "2.0.1")
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.5)
        raise RuntimeError(f"qwenpaw API did not become ready: {last_error}")
'''

REPLACEMENT = '''    async def _wait_for_qwenpaw_api(self) -> None:
        # Version readiness does not imply that the default Workspace is ready.
        # Only read-only management probes may be retried here; no model calls.
        last_error = None
        try:
            async with asyncio.timeout(120):
                while True:
                    if self._process is not None and self._process.returncode is not None:
                        raise RuntimeError(
                            f"qwenpaw app exited before API readiness: {self._process.returncode}",
                        )
                    try:
                        await asyncio.to_thread(self.api_client.require_version, "2.0.1")
                        await asyncio.to_thread(self.api_client.list_mcp)
                    except Exception as exc:
                        last_error = type(exc).__name__
                        await asyncio.sleep(0.5)
                        continue
                    if self._process is not None and self._process.returncode is not None:
                        raise RuntimeError(
                            f"qwenpaw app exited before API readiness: {self._process.returncode}",
                        )
                    return
        except TimeoutError:
            # Cancellation bounds this coroutine, not the already-running thread.
            # Its read-only socket can continue until the existing client timeout.
            raise RuntimeError(
                f"qwenpaw API workspace readiness exceeded 120 seconds; last error type: {last_error}",
            ) from None
'''


def patched_source(source):
    if source.count(ORIGINAL) != 1:
        raise ValueError("Expected exactly one pinned readiness method; source drift or already patched")
    result = source.replace(ORIGINAL, REPLACEMENT, 1)
    ast.parse(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    source = args.source.read_text(encoding="utf-8")
    result = patched_source(source)
    args.source.write_text(result, encoding="utf-8")
    print(json.dumps({"status": "source_patched_not_runtime_verified",
        "source_sha256_before": hashlib.sha256(source.encode()).hexdigest(),
        "source_sha256_after": hashlib.sha256(result.encode()).hexdigest()}))


if __name__ == "__main__":
    main()
