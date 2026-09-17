from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolRequest(BaseModel):
    incident_id: str = Field(min_length=3, max_length=128)
    scenario_id: str = Field(min_length=3, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = Field(default=None, min_length=3, max_length=128)


class Evidence(BaseModel):
    evidence_id: str
    incident_id: str
    run_id: str | None = None
    scenario_id: str | None = None
    tool_call_id: str | None = None
    environment: Literal["fixture", "lab", "live", "unknown"] = "unknown"
    execution: Literal["simulated", "real", "unknown"] = "unknown"
    envelope_sha256: str | None = None
    source: str
    collected_at: str
    observed_at: str | None = None
    kind: str
    summary: str
    data: dict[str, Any]
    sha256: str
    confidence: float = Field(ge=0, le=1)
    supports: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
    handling: Literal["public", "internal", "restricted"] = "internal"
    standard: dict[str, Any]
    entities: list[dict[str, str]] = Field(default_factory=list)
    observables: list[dict[str, str]] = Field(default_factory=list)
    attack_techniques: list[str] = Field(default_factory=list)
    quality: dict[str, Any]


class ToolResponse(BaseModel):
    ok: bool = True
    tool: str
    evidence: Evidence


class EvidenceValidationRequest(BaseModel):
    evidence_ids: list[str] = Field(min_length=1, max_length=128)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=512)
    limit: int = Field(default=5, ge=1, le=10)


class WorkflowTransitionRequest(BaseModel):
    session_id: str = Field(min_length=3, max_length=128)
    state: Literal[
        "received", "investigating", "evidence_validation", "awaiting_approval",
        "approved", "executing", "completed", "rejected", "failed", "timed_out",
    ]
    actor: str = Field(min_length=2, max_length=128)
    message: str = Field(default="", max_length=1024)
