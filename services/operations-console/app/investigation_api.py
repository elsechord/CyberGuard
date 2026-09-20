"""Asynchronous task API; materials are data, never tool authority."""
import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from . import errors, intake, jobs
from .api import require_scope

router = APIRouter(prefix="/api/v1/investigations", tags=["investigations"])


async def read_submission(request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise errors.invalid_request("Content-Type must be application/json", status=415)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > intake.MAX_SUBMISSION_BYTES:
            raise errors.invalid_request("Submission exceeds 1 MiB", status=413)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    def reject_constant(_value):
        raise ValueError("non-finite number")
    try:
        return json.loads(body, object_pairs_hook=unique, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise errors.invalid_request("Invalid JSON object or duplicate keys", status=422) from None


@router.post("")
async def submit(request: Request):
    principal = require_scope(request, "investigations:write")
    payload = await read_submission(request)
    job, replayed = await run_in_threadpool(jobs.submit, principal, payload, request.headers.get("idempotency-key", ""))
    return JSONResponse({"data": job}, status_code=202,
                        headers={"Location": job["links"]["self"], "Retry-After": "3", "Idempotent-Replay": str(replayed).lower()})


@router.get("")
def list_jobs(request: Request, limit: int = 50, cursor: str | None = None):
    principal = require_scope(request, "investigations:read")
    bounded = max(1, min(limit, 100))
    rows = jobs.list_jobs(principal, bounded + 1, cursor)
    more = len(rows) > bounded
    return {"data": rows[:bounded], "has_more": more, "next_cursor": rows[bounded-1]["id"] if more else None}


@router.get("/{job_id}")
def get_job(request: Request, job_id: str):
    principal = require_scope(request, "investigations:read")
    job = jobs.get_job(principal, job_id)
    return JSONResponse({"data": job}, headers={"Retry-After": "3"} if job["status"] not in jobs.TERMINAL else {})


@router.post("/{job_id}/cancel")
def cancel(request: Request, job_id: str):
    principal = require_scope(request, "investigations:write")
    return {"data": jobs.cancel(principal, job_id)}


@router.get("/{job_id}/report")
def export_report(request: Request, job_id: str):
    principal = require_scope(request, "investigations:read")
    job = jobs.get_job(principal, job_id)
    if job["status"] != "completed" or job["report"] is None:
        raise errors.invalid_request("Investigation report is not ready", "report_not_ready", status=409)
    return JSONResponse({"job_id": job["id"], "report": job["report"], "runtime": job["runtime"]},
                        headers={"Content-Disposition": f'attachment; filename="{job["id"]}-report.json"'})
