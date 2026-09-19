"""CyberGuard Operations Console — multi-user operator surface.

FastAPI service on internal port 8080 (compose maps 127.0.0.1:18120).
Session + API-key authentication, deny-by-default RBAC, CSRF-protected forms,
strict security headers and a JSON API v1 with envelope responses.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, db, errors, idempotency
from . import api as api_module
from . import pages as pages_module

logger = logging.getLogger("cyberguard.console")

# Import-time initialization matches the repository's other services, so the
# TestClient can exercise the app without a lifespan context.
db.init_db()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    idempotency.purge_expired()
    token = auth.ensure_setup_token()
    if token:
        logger.warning(
            "CYBERGUARD SETUP: no users found. A one-time setup token has been "
            "issued; open /setup and paste the token from this log line.")
        print("CYBERGUARD SETUP TOKEN (first boot only): " + token, flush=True)
    else:
        logger.info("operations console started with %d existing user(s)",
                    auth.user_count())
    yield


app = FastAPI(
    title="CyberGuard Operations Console",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(api_module.router)
app.include_router(pages_module.router)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
       "img-src 'self' data:; connect-src 'self'; form-action 'self'; "
       "frame-ancestors 'none'; base-uri 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(errors.ApiError)
async def api_error_handler(_request: Request, exc: errors.ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"type": exc.error_type, "code": exc.code,
                           "message": exc.message}},
        headers=exc.headers or {},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "body"
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_request_error",
                           "code": "validation_error",
                           "message": f"invalid {field}"}},
    )
