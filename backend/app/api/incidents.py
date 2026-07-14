from typing import Any

from fastapi import APIRouter

from app.contracts import (
    AuditRecord,
    EvidenceItem,
    ExplanationOutput,
    Hypothesis,
    IncidentSummary,
    InvestigationResponse,
    PlaybookRecommendation,
    ReviewRecord,
    ReviewRequest,
)

from .stubs import feature_not_implemented


router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=dict[str, Any])
def list_incidents() -> dict[str, Any]:
    feature_not_implemented("Persons 4 and 5")


@router.get("/{incident_id}/investigation", response_model=InvestigationResponse)
def investigation(incident_id: str) -> InvestigationResponse:
    del incident_id
    feature_not_implemented("Person 5")


@router.get("/{incident_id}/timeline", response_model=dict[str, Any])
def timeline(incident_id: str) -> dict[str, Any]:
    del incident_id
    feature_not_implemented("Persons 4 and 5")


@router.get("/{incident_id}/hypotheses", response_model=list[Hypothesis])
def hypotheses(incident_id: str) -> list[Hypothesis]:
    del incident_id
    feature_not_implemented("Person 4")


@router.get("/{incident_id}/evidence", response_model=dict[str, list[EvidenceItem]])
def evidence(incident_id: str) -> dict[str, list[EvidenceItem]]:
    del incident_id
    feature_not_implemented("Person 5")


@router.get(
    "/{incident_id}/recommendations",
    response_model=dict[str, list[PlaybookRecommendation]],
)
def recommendations(incident_id: str) -> dict[str, list[PlaybookRecommendation]]:
    del incident_id
    feature_not_implemented("Person 5")


@router.get("/{incident_id}/explanation", response_model=ExplanationOutput)
def explanation(incident_id: str) -> ExplanationOutput:
    del incident_id
    feature_not_implemented("Person 5")


@router.get("/{incident_id}/audit", response_model=list[AuditRecord])
def audit(incident_id: str) -> list[AuditRecord]:
    del incident_id
    feature_not_implemented("Person 5")


@router.post("/{incident_id}/recompute", response_model=dict[str, Any])
def recompute(incident_id: str) -> dict[str, Any]:
    del incident_id
    feature_not_implemented("Persons 1 and 4")


@router.post("/{incident_id}/review", response_model=ReviewRecord)
def review(incident_id: str, _review: ReviewRequest) -> ReviewRecord:
    del incident_id
    feature_not_implemented("Person 5")


@router.get("/{incident_id}", response_model=IncidentSummary)
def incident_summary(incident_id: str) -> IncidentSummary:
    del incident_id
    feature_not_implemented("Person 4")
