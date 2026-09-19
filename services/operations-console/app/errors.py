"""Unified API v1 error envelope and pagination helpers.

Every JSON error has the shape:
    {"error": {"type": "...", "code": "...", "message": "..."}}
with type in invalid_request_error | authentication_error | permission_error |
idempotency_error | api_error.
"""
from fastapi import HTTPException
from fastapi.responses import JSONResponse


def api_error(status: int, error_type: str, code: str, message: str,
              headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "code": code, "message": message}},
        headers=headers or {},
    )


class ApiError(HTTPException):
    def __init__(self, status: int, error_type: str, code: str, message: str,
                 headers: dict | None = None):
        super().__init__(status_code=status, detail=message, headers=headers)
        self.error_type = error_type
        self.code = code
        self.message = message


def invalid_request(message: str, code: str = "invalid_request",
                    status: int = 400) -> ApiError:
    return ApiError(status, "invalid_request_error", code, message)


def authentication_error(message: str = "authentication required",
                         code: str = "missing_credentials") -> ApiError:
    return ApiError(401, "authentication_error", code, message,
                    headers={"WWW-Authenticate": "Bearer"})


def permission_error(message: str = "insufficient permission",
                     code: str = "forbidden") -> ApiError:
    return ApiError(403, "permission_error", code, message)


def idempotency_error(message: str) -> ApiError:
    return ApiError(409, "idempotency_error", "idempotency_key_conflict", message)


def api_error_from(message: str = "upstream failure") -> ApiError:
    return ApiError(502, "api_error", "upstream_unavailable", message)


def envelope(items: list, *, limit: int, cursor_of) -> dict:
    """cursor_of(item) returns that item's cursor token (id string)."""
    has_more = len(items) > limit
    page = items[:limit]
    next_cursor = cursor_of(page[-1]) if has_more and page else None
    return {"data": page, "has_more": has_more, "next_cursor": next_cursor}


def clamp_limit(value: int | None) -> int:
    if value is None:
        return 20
    if value < 1:
        raise invalid_request("limit must be >= 1", "invalid_limit")
    return min(value, 100)
