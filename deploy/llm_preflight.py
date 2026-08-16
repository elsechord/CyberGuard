#!/usr/bin/env python3
"""Small, secret-safe OpenAI-compatible provider preflight."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


class LLMPreflightError(RuntimeError):
    def __init__(self, category: str, message: str, *, status: int | None = None):
        super().__init__(message)
        self.category = category
        self.status = status


def _safe_body(body: bytes, api_key: str) -> str:
    text = body.decode("utf-8", errors="replace").strip().replace(api_key, "[REDACTED]")
    return text[:500] + ("...(truncated)" if len(text) > 500 else "")


def _status_category(status: int) -> tuple[str, str, bool]:
    if status == 401:
        return "authentication", "API key was rejected", False
    if status == 403:
        return "authorization", "account or model permission was rejected", False
    if status == 402:
        return "billing", "provider balance is insufficient", False
    if status == 404:
        return "routing", "base URL or endpoint was not found", False
    if status == 422:
        return "request", "model name or request parameters were rejected", False
    if status == 429:
        return "rate_limit", "provider is rate limiting the request", True
    if status >= 500:
        return "provider_unavailable", "provider returned a server error", True
    return "provider_rejected", "provider rejected the request", False


def probe_provider(
    base_url: str,
    api_key: str,
    model: str,
    *,
    timeout: float = 45,
    retries: int = 2,
    opener=urllib.request.urlopen,
    sleep=time.sleep,
) -> None:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with only: ok"}],
            "max_tokens": 1,
            "stream": False,
        },
        separators=(",", ":"),
    ).encode()

    for attempt in range(retries + 1):
        request = urllib.request.Request(
            endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "User-Agent": "CyberGuard/llm-preflight",
            },
        )
        try:
            with opener(request, timeout=timeout) as response:
                if 200 <= response.status < 300:
                    return
                status = response.status
                body = response.read(4096)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read(4096)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            if attempt < retries:
                sleep(0.5 * (2**attempt))
                continue
            raise LLMPreflightError(
                "transport",
                f"provider transport failed before authentication: {type(exc).__name__}",
            ) from exc

        category, hint, retryable = _status_category(status)
        if retryable and attempt < retries:
            sleep(0.5 * (2**attempt))
            continue
        safe = _safe_body(body, api_key)
        suffix = f"; response={safe}" if safe else ""
        raise LLMPreflightError(category, f"HTTP {status}: {hint}{suffix}", status=status)


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Secret-safe LLM provider preflight")
    parser.add_argument("--env", type=Path, required=True, help="AgentTeams environment file")
    args = parser.parse_args()
    values = _read_env(args.env)
    base_url = values.get("AGENTTEAMS_OPENAI_BASE_URL", "")
    api_key = values.get("AGENTTEAMS_LLM_API_KEY", "")
    model = values.get("AGENTTEAMS_DEFAULT_MODEL", "")
    if not base_url or len(api_key) < 8 or not model:
        raise SystemExit("LLM preflight configuration is incomplete")
    print(f"provider_preflight base_url={base_url} model={model}", flush=True)
    try:
        probe_provider(base_url, api_key, model)
    except LLMPreflightError as exc:
        raise SystemExit(f"provider_preflight=FAIL category={exc.category} detail={exc}") from exc
    print("provider_preflight=PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
