import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import (EvidenceValidationRequest, KnowledgeSearchRequest, ToolRequest,
                     ToolResponse, WorkflowTransitionRequest)
from .store import store
from .connectors import ConnectorError, live_connectors
from .knowledge import knowledge_store
from . import run_view
from .investigation import router as investigation_router

app = FastAPI(
    title="CyberGuard Security Tool Gateway",
    version="0.11.0",
    description="Read-only evidence collection tools for AgentTeams Workers.",
    docs_url=None,
    redoc_url=None,
)
STATIC_DIR = Path(__file__).parent / "static"
app.include_router(investigation_router)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path == "/console" or request.url.path.startswith("/assets/"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith(("/incidents", "/evidence", "/tools/", "/investigations/")):
        response.headers["Cache-Control"] = "no-store"
    return response


def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("CYBERGUARD_API_TOKEN", "")
    supplied = (authorization or "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "security-tool-gateway"}


@app.get("/console", include_in_schema=False)
def console() -> FileResponse:
    return FileResponse(STATIC_DIR / "console.html")


@app.get("/tools", dependencies=[Depends(authorize)])
def list_tools() -> dict[str, list[str]]:
    return {
        "tools": [
            "alert.snapshot",
            "intel.lookup",
            "network.search",
            "boundary.policy",
            "endpoint.timeline",
            "asset.context",
            "recovery.metrics",
            "evidence.validate",
            "knowledge.search",
        ],
        "live_connectors": live_connectors.configured_tools(),
    }


@app.get("/evidence/{incident_id}", dependencies=[Depends(authorize)])
def evidence_for_incident(incident_id: str) -> dict:
    return {"incident_id": incident_id, "evidence": store.list_evidence(incident_id)}


@app.post("/evidence/{incident_id}/validate", dependencies=[Depends(authorize)])
def validate_evidence_for_incident(incident_id: str, request: EvidenceValidationRequest) -> dict:
    return store.validate_evidence_ids(incident_id, request.evidence_ids)


@app.post("/knowledge/search", dependencies=[Depends(authorize)])
def search_knowledge(request: KnowledgeSearchRequest) -> dict:
    return {
        "query": request.query,
        "results": knowledge_store.search(request.query, request.limit),
        "notice": "知识检索结果不能作为当前事件事实；关键结论仍必须引用 Evidence ID。",
    }


@app.post("/incidents/{incident_id}/workflow", dependencies=[Depends(authorize)])
def transition_workflow(incident_id: str, request: WorkflowTransitionRequest) -> dict:
    try:
        return store.transition_workflow(incident_id, request.session_id, request.state,
                                         request.actor, request.message)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/incidents/{incident_id}/workflow", dependencies=[Depends(authorize)])
def workflow(incident_id: str, session_id: str | None = None) -> dict:
    result = store.workflow(incident_id, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    return result


@app.get("/incidents", dependencies=[Depends(authorize)])
def incidents() -> dict:
    return {"incidents": store.list_incidents()}


@app.get("/incidents/{incident_id}", dependencies=[Depends(authorize)])
def incident(incident_id: str) -> dict:
    evidence = store.list_evidence(incident_id)
    actions = store.list_actions(incident_id)
    workflow_state = store.workflow(incident_id)
    if not evidence and not actions and workflow_state is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return {
        "summary": store.incident_summary(incident_id),
        "evidence": evidence,
        "actions": actions,
        "workflow": workflow_state,
        "runs": sorted({e["run_id"] for e in evidence if e.get("run_id")}),
    }


@app.get("/incidents/{incident_id}/runs/{run_id}", dependencies=[Depends(authorize)])
def incident_run(incident_id: str, run_id: str) -> dict:
    if not 3 <= len(run_id) <= 128:
        raise HTTPException(status_code=422, detail="invalid run_id")
    evidence = [e for e in store.list_evidence(incident_id) if e.get("run_id") == run_id]
    result = run_view.build(incident_id, run_id, evidence)
    if not evidence and not result["actions"] and result["audit_status"] == "valid":
        raise HTTPException(status_code=404, detail="run not found")
    return result


@app.get("/incidents/{incident_id}/graph", dependencies=[Depends(authorize)])
def incident_graph(incident_id: str) -> dict:
    graph = store.incident_graph(incident_id)
    if len(graph["nodes"]) == 1:
        raise HTTPException(status_code=404, detail="incident not found")
    return graph


@app.get("/incidents/{incident_id}/quality", dependencies=[Depends(authorize)])
def incident_quality(incident_id: str) -> dict:
    result = store.incident_quality(incident_id)
    if result["evidence_count"] == 0:
        raise HTTPException(status_code=404, detail="incident not found")
    return result


@app.post("/tools/{namespace}/{function}", response_model=ToolResponse, dependencies=[Depends(authorize)])
def invoke(namespace: str, function: str, request: ToolRequest) -> ToolResponse:
    tool = f"{namespace}.{function}"
    try:
        evidence = store.collect(
            incident_id=request.incident_id,
            scenario_id=request.scenario_id,
            tool=tool,
            arguments=request.arguments,
            run_id=request.run_id,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="scenario not found") from None
    except KeyError:
        raise HTTPException(status_code=404, detail="tool unavailable for scenario") from None
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return ToolResponse(tool=tool, evidence=evidence)
