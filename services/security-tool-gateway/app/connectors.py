import json
import os
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


class ConnectorError(RuntimeError):
    pass


class LiveConnectorRegistry:
    """Server-owned connector configuration. Agents can supply query arguments, never destinations or secrets."""

    def __init__(self) -> None:
        self.config_path = Path(
            os.getenv("CYBERGUARD_LIVE_CONNECTORS_FILE", "/app/config/connectors.json")
        )

    def configured_tools(self) -> list[str]:
        return sorted(self._load().keys())

    def invoke(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        definition = self._load().get(tool)
        if definition is None:
            raise ConnectorError(f"live connector is not configured for {tool}")

        base_url = os.getenv(definition.get("base_url_env", ""), "")
        if not base_url:
            raise ConnectorError(f"missing server-side base URL for {tool}")
        parsed = urlparse(base_url)
        allow_http = os.getenv("CYBERGUARD_ALLOW_INSECURE_HTTP", "0") == "1"
        if parsed.scheme not in ({"https", "http"} if allow_http else {"https"}):
            raise ConnectorError("connector URL must use HTTPS")
        if parsed.username or parsed.password or not parsed.hostname:
            raise ConnectorError("connector URL must not contain credentials")

        path = str(definition.get("path", ""))
        if not path.startswith("/") or ".." in path:
            raise ConnectorError("connector path must be an absolute safe path")
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        method = str(definition.get("method", "POST")).upper()
        if method not in {"POST", "GET"}:
            raise ConnectorError("only GET and POST connectors are supported")

        headers = {"Accept": "application/json", "User-Agent": "CyberGuard/0.2"}
        token_env = definition.get("token_env")
        if token_env:
            token = os.getenv(str(token_env), "")
            if not token:
                raise ConnectorError(f"missing server-side credential for {tool}")
            header_name = str(definition.get("auth_header", "Authorization"))
            prefix = str(definition.get("auth_prefix", "Bearer "))
            headers[header_name] = prefix + token

        body = None
        if method == "POST":
            body = json.dumps(arguments, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif arguments:
            raise ConnectorError("GET connector arguments are disabled to prevent unsafe URL construction")

        request = Request(url=url, data=body, headers=headers, method=method)
        timeout = min(max(float(definition.get("timeout_seconds", 10)), 1), 30)
        try:
            with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
                payload = response.read(2_000_001)
        except HTTPError as exc:
            raise ConnectorError(f"upstream returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise ConnectorError("upstream connector is unavailable") from exc
        if len(payload) > 2_000_000:
            raise ConnectorError("upstream response exceeds 2 MB")
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorError("upstream did not return valid UTF-8 JSON") from exc

        return self._normalize(tool, raw, definition)

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.config_path.is_file():
            return {}
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        connectors = data.get("connectors", {})
        if not isinstance(connectors, dict):
            raise ConnectorError("connectors configuration must be an object")
        return connectors

    @staticmethod
    def _normalize(tool: str, raw: Any, definition: dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, dict) and {"summary", "data"}.issubset(raw):
            result = dict(raw)
        else:
            count = len(raw) if isinstance(raw, list) else 1
            result = {
                "summary": f"Live connector {tool} returned {count} record(s).",
                "data": {"records": raw} if isinstance(raw, list) else {"record": raw},
            }
        # Provenance and handling are trust-boundary fields. The upstream payload is
        # untrusted data and must not be able to forge an independent source or
        # downgrade a server-configured classification.
        result["source"] = definition.get("source", f"live:{tool}")
        result.setdefault("kind", definition.get("kind", tool))
        result.setdefault("confidence", 0.7)
        result.setdefault("supports", [])
        result.setdefault("contradicts", [])
        result["handling"] = definition.get("handling", "restricted")
        return result


live_connectors = LiveConnectorRegistry()
