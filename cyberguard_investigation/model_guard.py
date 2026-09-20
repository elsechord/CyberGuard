"""Run-bound model admission. Buffered upstream calls; no automatic retries."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import FastAPI, HTTPException, Request as WebRequest
from fastapi.responses import JSONResponse, Response

from .admission import AdmissionError, AdmissionLedger
from .evidence import canonical_bytes
from .model_runner import redact_tree, strict_json

MAX_BODY = 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
FIELDS = {"model", "messages", "tools", "tool_choice", "parallel_tool_calls", "temperature", "top_p",
          "max_tokens", "max_completion_tokens", "stream", "stream_options", "stop", "presence_penalty",
          "frequency_penalty", "response_format", "reasoning_effort", "seed", "n"}


def sanitized(value, secrets):
    variants = []
    for secret in secrets:
        for _ in range(4):
            variants.append(secret)
            secret = json.dumps(secret, ensure_ascii=True)[1:-1]
    return redact_tree(value, sorted(set(variants), key=len, reverse=True))


def validate_message(response):
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise GuardError("provider_message_invalid")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant" or not isinstance(choice.get("finish_reason"), str):
        raise GuardError("provider_message_invalid")
    for key in ("content", "reasoning_content", "refusal"):
        if message.get(key) is not None and not isinstance(message[key], str):
            raise GuardError("provider_message_invalid")
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or len(calls) > 32:
        raise GuardError("provider_message_invalid")
    for call in calls:
        if (not isinstance(call, dict) or call.get("type") != "function" or not isinstance(call.get("id"), str)
                or not isinstance(call.get("function"), dict) or not isinstance(call["function"].get("name"), str)
                or not isinstance(call["function"].get("arguments"), str)):
            raise GuardError("provider_message_invalid")


class GuardError(Exception):
    def __init__(self, code, details=None):
        self.code = code
        # Optional non-secret diagnostic record (e.g. offending tool names) for
        # operator review; the HTTP response never exposes it.
        self.details = details
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def provider_call(endpoint, key, payload, timeout):
    request = Request(endpoint, data=canonical_bytes(payload),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    # HTTP errors/redirects are handled by the caller without exposing response bodies.
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise GuardError("provider_response_too_large")
    result = strict_json(raw)
    if not isinstance(result, dict):
        raise GuardError("provider_response_invalid")
    return result


def repeated_tool_error(messages):
    """Only explicit structured tool failures; never scan evidence prose for commands."""
    names, failures = {}, {}
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict) and isinstance(call.get("function"), dict):
                    names[call.get("id")] = call["function"].get("name", "unknown")
        if message.get("role") != "tool" or not isinstance(message.get("content"), str):
            continue
        try:
            value = strict_json(message["content"])
        except (ValueError, TypeError, RecursionError):
            continue
        if not isinstance(value, dict) or not (value.get("isError") is True or value.get("error") or value.get("ok") is False):
            continue
        error = value.get("error")
        code = error.get("code", "structured_tool_error") if isinstance(error, dict) else value.get("type", "structured_tool_error")
        fingerprint = (str(names.get(message.get("tool_call_id"), "unknown"))[:128], str(code)[:128])
        failures[fingerprint] = failures.get(fingerprint, 0) + 1
        if failures[fingerprint] >= 2:
            return True
    return False


class ModelGuard:
    def __init__(self, config, directory, *, transport=None):
        self.config = config
        canonical_bytes(config)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.run_id = config["run_id"]
        self.roles = config["roles"]
        self.tool_policy = config.get("tool_policy", "guard")
        if self.tool_policy not in {"guard", "runtime"}:
            raise ValueError("tool_policy must be guard or runtime")
        self.model = config["model"]
        endpoint = urlsplit(config["upstream_endpoint"])
        if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password
                or endpoint.query or endpoint.fragment):
            raise ValueError("Explicit fixed HTTPS upstream required")
        if not isinstance(self.roles, dict) or not 1 <= len(self.roles) <= 16:
            raise ValueError("Bounded roles required")
        credentials = {role: item["token"] for role, item in self.roles.items()}
        self.secrets = [config["upstream_key"], config["admin_token"], *credentials.values()]
        if any(not isinstance(value, str) or len(value) < 32 for value in self.secrets) or len(set(self.secrets)) != len(self.secrets):
            raise ValueError("Distinct strong credentials required")
        self.max_output = config.get("max_output_per_request", 4096)
        self.input_overhead = config.get("input_overhead_reservation", 2048)
        self.timeout = config.get("upstream_timeout_seconds", 90)
        if (type(self.max_output) is not int or not 1 <= self.max_output <= 8192
                or type(self.input_overhead) is not int or not 1024 <= self.input_overhead <= 16384
                or type(self.timeout) is not int or not 1 <= self.timeout <= 120):
            raise ValueError("Invalid request bounds")
        self.ledger = AdmissionLedger(self.directory / "admission.sqlite")
        self.ledger.create_run(self.run_id, model=self.model, evidence_hash=config["evidence_hash"],
                               limits=config["limits"], role_credentials=credentials)
        config_hash = hashlib.sha256(canonical_bytes(config)).hexdigest()
        with closing(sqlite3.connect(self.ledger.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS guard_config_bindings (run_id TEXT PRIMARY KEY, config_sha256 TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO guard_config_bindings VALUES (?,?)", (self.run_id, config_hash))
            if db.execute("SELECT config_sha256 FROM guard_config_bindings WHERE run_id=?", (self.run_id,)).fetchone()[0] != config_hash:
                raise ValueError("Immutable model guard configuration changed; use a new run")
        self.transport = transport or provider_call
        # Arming is process-local on purpose: every restart requires operator revalidation.
        self.armed = False
        self.state_lock = threading.RLock()
        self.denials = {}
        self.denial_details = []

    def identity(self, authorization):
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        for role, settings in self.roles.items():
            if hmac.compare_digest(token.encode(), settings["token"].encode()):
                if self.ledger.authenticate(self.run_id, role, token):
                    return role
        raise GuardError("invalid_role_credential")

    def admin(self, authorization):
        supplied = (authorization or "").removeprefix("Bearer ")
        if not hmac.compare_digest(supplied.encode(), self.config["admin_token"].encode()):
            raise GuardError("invalid_admin_credential")

    def snapshot(self):
        return {"run": self.ledger.get_run(self.run_id), "armed": self.armed,
                "denials": dict(self.denials), "denial_details": list(self.denial_details),
                "token_reservation_method": "serialized_utf8_bytes_plus_overhead",
                "limitations": ["Input reservation is conservative, not a verified provider tokenizer bound.",
                    "Already forwarded calls cannot be recalled; unknown usage keeps reservations.",
                    "Provider usage is reported, not independently metered billing."]}

    def deny(self, code, details=None):
        if len(self.denials) < 64 or code in self.denials:
            self.denials[code] = self.denials.get(code, 0) + 1
        if details is not None and len(self.denial_details) < 16:
            self.denial_details.append(details)

    def declaration(self, role, body):
        """No upstream request: retain only tool names and schema hashes for preflight."""
        if not isinstance(body, dict):
            return
        tools = body.get("tools") or []
        if not isinstance(tools, list) or len(tools) > 256:
            return
        items = []
        nonconforming = []
        for item in tools:
            function = item.get("function") if isinstance(item, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                if isinstance(function, dict):
                    nonconforming.append("malformed_name:" + repr(function.get("name"))[:96])
                else:
                    nonconforming.append("not_a_function_tool")
                continue
            name = function["name"]
            if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
                items.append({"name": name, "definition_sha256": hashlib.sha256(canonical_bytes(function)).hexdigest()})
            else:
                # Name-shape mismatches are the primary diagnosis target; keep a
                # bounded repr instead of silently dropping the observation.
                nonconforming.append(repr(name)[:128])
        self._write_trace("declaration-" + role, {"run_id": self.run_id, "role": role,
            "kind": "disarmed_tool_schema_observation", "forwarded": False, "tools": items,
            "nonconforming_tool_names": sorted(set(nonconforming))[:64]})

    def tool_denial_detail(self, role, tool_list, allowed):
        """Name-only diagnostic for a whitelist denial; never schemas or secrets."""
        names, malformed = [], 0
        if isinstance(tool_list, list):
            for item in tool_list[:512]:
                function = item.get("function") if isinstance(item, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                if isinstance(name, str):
                    names.append(name[:128])
                else:
                    malformed += 1
        allowed_names = [str(name)[:128] for name in allowed]
        return {"run_id": self.run_id, "role": role, "code": "tool_definition_not_allowed",
                "kind": "tool_whitelist_denial_detail",
                "requested_tool_names": sorted(set(names)),
                "offending_tool_names": sorted(set(names) - set(allowed_names)),
                "allowed_tool_names": sorted(set(allowed_names)),
                "malformed_tool_definitions": malformed,
                "request_tool_count": len(tool_list) if isinstance(tool_list, list) else None}

    def record_tool_denial(self, role, tool_list, allowed):
        """Persist the offending names durably (trace file) before the request is refused."""
        detail = self.tool_denial_detail(role, tool_list, allowed)
        fingerprint = "tool-denial-" + hashlib.sha256(
            (self.run_id + ":" + role + ":" + json.dumps(detail, sort_keys=True)).encode()).hexdigest()[:32]
        try:
            self._write_trace(fingerprint, detail)
        except Exception:
            pass  # The in-memory denial count and closed run remain authoritative.
        return detail

    def prepare(self, role, body):
        if not self.armed:
            raise GuardError("guard_not_armed")
        if not isinstance(body, dict) or not set(body) <= FIELDS:
            raise GuardError("unsupported_request_fields")
        if not isinstance(body.get("model"), str) or body["model"] not in {self.model, self.roles[role].get("model_alias", self.model)}:
            raise GuardError("model_not_bound")
        messages = body.get("messages")
        if not isinstance(messages, list) or not 1 <= len(messages) <= 256 or any(not isinstance(m, dict) for m in messages):
            raise GuardError("invalid_messages")
        # Validate history before the failure detector iterates calls or indexes IDs.
        # Null tool_calls is a normal assistant-message representation.
        for message in messages:
            if not isinstance(message.get("role"), str) or message["role"] not in {
                    "system", "developer", "user", "assistant", "tool", "function"}:
                raise GuardError("invalid_messages")
            calls = message.get("tool_calls")
            if calls is not None:
                if not isinstance(calls, list) or len(calls) > 32:
                    raise GuardError("invalid_messages")
                seen_ids = set()
                for call in calls:
                    if (not isinstance(call, dict) or not isinstance(call.get("id"), str)
                            or not call["id"].strip() or call["id"] in seen_ids
                            or call.get("type", "function") != "function"
                            or not isinstance(call.get("function"), dict)
                            or not isinstance(call["function"].get("name"), str)
                            or not call["function"]["name"].strip()
                            or not isinstance(call["function"].get("arguments"), str)):
                        raise GuardError("invalid_messages")
                    seen_ids.add(call["id"])
            if message["role"] == "tool" and (
                    not isinstance(message.get("tool_call_id"), str)
                    or not message["tool_call_id"].strip()):
                raise GuardError("invalid_messages")
        allowed = self.roles[role].get("allowed_tools")
        if self.tool_policy == "guard" and allowed is not None:
            tool_list = body.get("tools") or []
            if (not isinstance(tool_list, list) or any(not isinstance(t, dict) or t.get("type") != "function"
                    or not isinstance(t.get("function"), dict) or t["function"].get("name") not in allowed for t in tool_list)):
                raise GuardError("tool_definition_not_allowed",
                                 details=self.record_tool_denial(role, tool_list, allowed))
        if body.get("n", 1) != 1 or type(body.get("n", 1)) is not int:
            raise GuardError("multiple_completions_not_allowed")
        if self.tool_policy == "guard" and repeated_tool_error(messages):
            self.ledger.close_run(self.run_id, "repeated_structured_tool_failure")
            raise GuardError("repeated_structured_tool_failure")
        streaming = body.get("stream", False)
        if type(streaming) is not bool:
            raise GuardError("invalid_stream_flag")
        limit = body.get("max_completion_tokens", body.get("max_tokens", self.max_output))
        if type(limit) is not int or limit <= 0:
            raise GuardError("invalid_output_limit")
        payload = dict(body)
        payload.pop("stream_options", None)
        payload.pop("max_completion_tokens", None)
        payload.update(model=self.model, stream=False, max_tokens=min(limit, self.max_output))
        encoded = canonical_bytes(payload)
        if len(encoded) > MAX_BODY:
            raise GuardError("request_too_large")
        body_hash = hashlib.sha256(encoded).hexdigest()
        # Ignore untrusted client request IDs: changing an ID cannot replay identical work.
        request_id = hashlib.sha256((role + ":" + body_hash).encode()).hexdigest()
        reserved = self.ledger.reserve(self.run_id, role, request_id, body_hash,
            len(encoded) + self.input_overhead, payload["max_tokens"])
        if not reserved["forward"]:
            raise GuardError("duplicate_request_not_forwarded")
        return request_id, payload, streaming

    def _write_trace(self, request_id, record):
        value = sanitized(record, self.secrets)
        encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        path = self.directory / (request_id + ".json")
        temp = self.directory / (request_id + ".tmp")
        for attempt in range(3):
            try:
                temp.write_text(encoded + "\n", encoding="utf-8")
                temp.replace(path)
                return
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.025 * (attempt + 1))

    def execute(self, role, request_id, payload):
        """Entire network + final settlement runs in one thread even if client disconnects."""
        record = {"run_id": self.run_id, "role": role, "request_id": request_id,
                  "evidence_hash": self.config["evidence_hash"], "request": payload,
                  "request_body_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
                  "guard_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "credential_redaction": "known_literals_and_json_escaped_forms",
                  "upstream_status": "not_started", "usage": None}
        settled = False
        forwarded = False
        try:
            self._write_trace(request_id, record)
            record["upstream_status"] = "ready_to_dispatch"
            self._write_trace(request_id, record)
            # close and dispatch have an explicit linearization point in the ledger.
            # Calls committed here count as in flight and cannot be recalled.
            with self.state_lock:
                if not self.armed:
                    raise GuardError("run_stopped_before_dispatch")
                if not self.ledger.begin_dispatch(self.run_id, request_id)["dispatch"]:
                    raise GuardError("duplicate_dispatch_not_forwarded")
            forwarded = True
            response = self.transport(self.config["upstream_endpoint"], self.config["upstream_key"], payload, self.timeout)
            canonical_bytes(response)
            if not isinstance(response, dict) or len(canonical_bytes(response)) > MAX_RESPONSE:
                raise GuardError("invalid_provider_response")
            usage = response.get("usage")
            if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0 for k in ("prompt_tokens", "completion_tokens")):
                raise GuardError("provider_usage_unknown")
            settlement = self.ledger.settle(self.run_id, request_id, usage["prompt_tokens"], usage["completion_tokens"])
            settled = True
            record.update(response=response, usage=usage, settlement=settlement, upstream_status="settled")
            if settlement["run"]["status"] == "halted":
                raise GuardError("provider_exceeded_reservation")
            validate_message(response)
            declared = {item["function"]["name"] for item in payload.get("tools", [])
                        if isinstance(item, dict) and isinstance(item.get("function"), dict)}
            if any(call["function"]["name"] not in declared for call in response["choices"][0]["message"].get("tool_calls") or []):
                raise GuardError("provider_requested_undeclared_tool")
            self._write_trace(request_id, record)
            return sanitized(response, self.secrets)
        except Exception as exc:
            code = exc.code if isinstance(exc, (GuardError, AdmissionError)) else "provider_or_persistence_failure"
            # Even if storage fails, this live process must immediately stop admitting work.
            self.armed = False
            record.update(upstream_status="failed", failure=code, forwarded=forwarded)
            try:
                if not settled:
                    self.ledger.mark_unknown(self.run_id, request_id, code)
            except Exception:
                record["settlement_failure"] = "ledger_unavailable"
            try:
                self.ledger.close_run(self.run_id, code)
            except Exception:
                record["close_failure"] = "ledger_unavailable"
            try:
                self._write_trace(request_id, record)
            except Exception:
                pass  # Durable pending/unknown admission still prevents a second dispatch.
            raise GuardError(code) from None


def as_sse(response):
    common = {key: response[key] for key in ("id", "created", "model", "system_fingerprint") if key in response}
    common["object"] = "chat.completion.chunk"
    choice = response["choices"][0]
    message = choice["message"]
    delta = {key: message[key] for key in ("role", "content", "reasoning_content", "refusal") if key in message}
    if message.get("tool_calls"):
        delta["tool_calls"] = [{**call, "index": index} for index, call in enumerate(message["tool_calls"])]
    chunks = [dict(common, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
              dict(common, choices=[{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}]),
              dict(common, choices=[], usage=response["usage"])]
    return "".join("data: " + json.dumps(chunk, ensure_ascii=False, allow_nan=False) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def create_app(config, directory, *, transport=None):
    guard = ModelGuard(config, directory, transport=transport)
    app = FastAPI(title="CyberGuard model admission", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.guard = guard

    @app.exception_handler(GuardError)
    @app.exception_handler(AdmissionError)
    async def reject(request, exc):
        guard.deny(exc.code, getattr(exc, "details", None))
        # Avoid 409/429/5xx: common SDKs retry these automatically. No hidden paid retry.
        status = 401 if exc.code.startswith("invalid_") and "credential" in exc.code else 400
        return JSONResponse({"error": {"type": "cyberguard_admission", "code": exc.code,
            "message": "Request not completed. Inspect the operator run ledger; do not retry automatically."}}, status_code=status,
            headers={"Cache-Control": "no-store", "X-CyberGuard-Run": guard.run_id})

    @app.get("/health")
    def health():
        return {"status": "ok", "armed": guard.armed}

    @app.get("/v1/models")
    def models(request: WebRequest):
        role = guard.identity(request.headers.get("authorization"))
        return {"object": "list", "data": [{"id": guard.roles[role].get("model_alias", guard.model), "object": "model", "owned_by": "local-run"}]}

    @app.get("/admin/status")
    def status(request: WebRequest):
        guard.admin(request.headers.get("authorization"))
        return guard.snapshot()

    @app.post("/admin/arm")
    def arm(request: WebRequest):
        guard.admin(request.headers.get("authorization"))
        with guard.state_lock:
            state = guard.ledger.get_run(guard.run_id)
            if state["status"] != "open" or state["usage"]["concurrency_used"]:
                raise GuardError("closed_or_uncertain_run_cannot_rearm")
            if guard.tool_policy == "guard" and any(not value.get("allowed_tools") for value in guard.roles.values()):
                raise GuardError("tool_allowlist_not_configured")
            guard.armed = True
        return guard.snapshot()

    @app.post("/admin/close")
    def close(request: WebRequest):
        guard.admin(request.headers.get("authorization"))
        with guard.state_lock:
            guard.armed = False
            guard.ledger.close_run(guard.run_id, "operator_closed")
        return guard.snapshot()

    @app.post("/v1/chat/completions")
    async def completions(request: WebRequest):
        role = guard.identity(request.headers.get("authorization"))
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY:
                raise GuardError("request_too_large")
        try:
            body = strict_json(bytes(raw))
        except (ValueError, TypeError, RecursionError):
            raise GuardError("invalid_request_json") from None
        if not guard.armed:
            guard.declaration(role, body)
        request_id, payload, streaming = guard.prepare(role, body)
        response = await asyncio.to_thread(guard.execute, role, request_id, payload)
        headers = {"Cache-Control": "no-store", "X-CyberGuard-Run": guard.run_id, "X-CyberGuard-Request": request_id}
        return (Response(as_sse(response), media_type="text/event-stream", headers=headers) if streaming else
                JSONResponse(response, headers=headers))

    return app
