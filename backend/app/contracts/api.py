from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, JsonValue, field_validator

from .analysis import AnalysisRun
from .base import AuditActorType, TopologyRelation, UtcModel
from .evidence import EvidenceItem
from .events import CanonicalEvent
from .hypotheses import Hypothesis
from .incidents import IncidentSummary
from .reviews import ReviewRecord


class ErrorDetail(UtcModel):
    field: str | None = None
    reason_code: str


class ErrorBody(UtcModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorEnvelope(UtcModel):
    error: ErrorBody


class HealthResponse(UtcModel):
    status: Literal["ok"]


class ReadinessComponentError(UtcModel):
    status: Literal["error"]
    reason: str


class ReadinessResponse(UtcModel):
    status: Literal["ready", "not_ready"]
    generated_at: datetime
    components: dict[str, str | dict[str, str | bool] | ReadinessComponentError]


class ConceptAssistantRequest(UtcModel):
    question: str = Field(min_length=3, max_length=500)

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ConceptAssistantResponse(UtcModel):
    generated_at: datetime
    answer: str
    model: str
    context_used: Literal[False] = False


class AuditRecord(UtcModel):
    audit_id: str
    timestamp: datetime
    actor_type: AuditActorType
    actor_id: str | None
    action: str
    object_type: str
    object_id: str
    request_id: str
    analysis_run_id: str | None
    payload: dict[str, JsonValue]


class AuditListResponse(UtcModel):
    generated_at: datetime
    items: list[AuditRecord]
    next_cursor: str | None = None


class TopologyNode(UtcModel):
    id: str
    name: str
    type: str
    service: str
    criticality: str
    state: Literal["suspected_root", "primary_affected", "impact_path", "blast_radius"] | None = (
        None
    )


class TopologyEdge(UtcModel):
    source: str
    target: str
    relation_type: TopologyRelation
    relationship: str
    state: Literal["impact_path", "blast_radius"] | None = None


class TopologySnapshot(UtcModel):
    fixture_version: str
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


class TimelineItem(UtcModel):
    event: CanonicalEvent
    attachment_decision: Literal["attached", "excluded"]
    attachment_score: float
    attachment_reasons: list[str]
    hypothesis_relevance: dict[str, list[str]] = Field(default_factory=dict)


class TimelineResponse(UtcModel):
    generated_at: datetime
    items: list[TimelineItem]


class RecomputeResponse(UtcModel):
    request_id: str
    generated_at: datetime
    analysis_run_id: str


class TopologyPathResponse(UtcModel):
    source: str
    target: str
    relation_type: TopologyRelation
    direction: Literal["forward", "reverse"]
    distance: int = Field(ge=0)
    entity_ids: list[str]


class BlastRadiusResponse(UtcModel):
    root_entity_id: str
    mode: Literal["dependency", "traffic"]
    relation_type: TopologyRelation
    direction: Literal["forward", "reverse"]
    max_hops: int = Field(ge=1)
    entity_ids: list[str]


class PlaybookRecommendation(UtcModel):
    recommendation_id: str
    analysis_run_id: str
    incident_id: str
    hypothesis_id: str
    step_id: str
    title: str
    step_type: Literal["diagnostic", "remediation"]
    risk_level: Literal["low", "medium", "high"]
    requires_human_approval: bool
    instructions: str
    rationale: str


class ExplanationClaim(UtcModel):
    claim: str
    evidence_ids: list[str] = Field(min_length=1)


class ExplanationOutput(UtcModel):
    analysis_run_id: str
    incident_id: str
    hypothesis_id: str
    generator: Literal["template", "llm"]
    summary: str
    claims: list[ExplanationClaim]
    diagnostic_step_ids: list[str]
    remediation_step_ids: list[str]


class InvestigationResponse(UtcModel):
    generated_at: datetime
    analysis_run_id: str
    analysis_run: AnalysisRun
    incident: IncidentSummary
    timeline: list[TimelineItem]
    topology: TopologySnapshot
    hypotheses: list[Hypothesis]
    evidence_by_hypothesis: dict[str, list[EvidenceItem]]
    recommendations_by_hypothesis: dict[str, list[PlaybookRecommendation]]
    explanation: ExplanationOutput
    reviews: list[ReviewRecord]

    def assert_consistent_run(self) -> None:
        if self.analysis_run.analysis_run_id != self.analysis_run_id:
            raise ValueError("analysis_run does not match response envelope")
        if self.incident.current_analysis_run_id != self.analysis_run_id:
            raise ValueError("incident does not point to response analysis run")
        run_scoped: list[Any] = [*self.hypotheses, *self.reviews]
        run_scoped.extend(item for items in self.evidence_by_hypothesis.values() for item in items)
        run_scoped.extend(
            item for items in self.recommendations_by_hypothesis.values() for item in items
        )
        run_scoped.append(self.explanation)
        if any(item.analysis_run_id != self.analysis_run_id for item in run_scoped):
            raise ValueError("run-scoped response object uses a different analysis_run_id")
