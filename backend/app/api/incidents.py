from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from itertools import pairwise
from typing import Annotated, Any, Never

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    AnalysisRun,
    AuditRecord,
    CanonicalEvent,
    EvidenceItem,
    ExplanationOutput,
    Hypothesis,
    IncidentSummary,
    IncidentStatus,
    InvestigationResponse,
    PlaybookRecommendation,
    ReviewMutationResponse,
    ReviewRecord,
    ReviewRequest,
    TimelineItem,
    TopologyRelation,
    TopologySnapshot,
)
from app.db import models
from app.db.repositories import (
    AnalysisRunRepository,
    EvidenceRepository,
    EventRepository,
    HypothesisRepository,
    IncidentRepository,
    ReviewRepository,
)
from app.orchestration.orchestrator import orchestrator
from app.playbooks.engine import get_step
from app.audit.service import audit_service
from app.reviews.service import ReviewServiceError, review_service
from app.topology.graph import TopologyPathNotFoundError, get_topology_graph

from .dependencies import get_session


router = APIRouter(prefix="/incidents", tags=["incidents"])
DatabaseSession = Annotated[Session, Depends(get_session)]


def _api_error(status_code: int, code: str, message: str, **details: Any) -> Never:
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": [
                {"field": field, "reason_code": str(reason)}
                for field, reason in details.items()
            ],
        },
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _incident_contract(row: models.Incident) -> IncidentSummary:
    return IncidentSummary(
        incident_id=row.id,
        current_analysis_run_id=row.current_analysis_run_id,
        title=row.title,
        status=row.status,
        severity=row.severity,
        started_at=_utc(row.started_at),
        last_event_at=_utc(row.last_event_at),
        primary_entity_id=row.primary_entity_id,
        affected_entity_ids=list(row.affected_entity_ids or []),
        anomaly_count=row.anomaly_count,
        top_hypothesis_id=row.top_hypothesis_id,
        confirmed_hypothesis_id=row.confirmed_hypothesis_id,
    )


def _run_contract(row: models.AnalysisRun) -> AnalysisRun:
    return AnalysisRun(
        analysis_run_id=row.id,
        incident_id=row.incident_id,
        revision=row.revision,
        status=row.status,
        trigger_event_id=row.trigger_event_id,
        input_fingerprint=row.input_fingerprint,
        created_at=_utc(row.created_at),
        completed_at=_utc(row.completed_at) if row.completed_at else None,
        algorithm_version=row.algorithm_version,
    )


def _hypothesis_contract(row: models.Hypothesis) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=row.id,
        analysis_run_id=row.analysis_run_id,
        incident_id=row.incident_id,
        hypothesis_type=row.type,
        candidate_entity_id=row.candidate_entity_id,
        rank=row.rank,
        evidence_score=row.evidence_score,
        evidence_coverage=row.coverage,
        factor_scores=row.factor_scores,
        summary=row.summary,
    )


def _evidence_contract(row: models.Evidence) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=row.id,
        analysis_run_id=row.analysis_run_id,
        incident_id=row.incident_id,
        hypothesis_id=row.hypothesis_id,
        kind=row.kind,
        source_event_id=row.source_event_id,
        statement=row.statement,
        relevance=row.relevance,
        reason_code=row.reason_code,
        created_at=_utc(row.created_at),
    )


def _event_contract(row: models.Event) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=row.id,
        timestamp=_utc(row.timestamp),
        ingested_at=_utc(row.ingested_at),
        entity_id=row.entity_id,
        modality=row.modality,
        event_type=row.event_type,
        severity=row.severity,
        signal_name=row.signal_name,
        signal_value=row.signal_value,
        unit=row.unit,
        trace_or_session_id=row.trace_or_session_id,
        source=row.source,
        source_record_id=row.source_record_id,
        schema_version=row.schema_version,
        quality_flags=list(row.quality_flags or []),
        raw_payload=dict(row.raw_payload or {}),
    )


def _review_contract(row: models.Review) -> ReviewRecord:
    return ReviewRecord(
        review_id=row.id,
        incident_id=row.incident_id,
        analysis_run_id=row.analysis_run_id,
        hypothesis_id=row.hypothesis_id,
        decision=row.decision,
        client_action_id=row.client_action_id,
        requested_evidence_id=row.requested_evidence_id,
        reviewer=row.reviewer,
        comment=row.comment,
        created_at=_utc(row.created_at),
    )


def _current_context(
    session: Session, incident_id: str
) -> tuple[models.Incident, models.AnalysisRun, str]:
    incident = IncidentRepository(session).get_by_id(incident_id)
    if incident is None:
        _api_error(
            http_status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            f"Incident not found: {incident_id}",
        )

    # Read the pointer once. Every child query in this request uses this local
    # immutable value rather than independently selecting a "latest" row.
    run_id = incident.current_analysis_run_id
    if run_id is None:
        _api_error(
            http_status.HTTP_409_CONFLICT,
            "ANALYSIS_NOT_AVAILABLE",
            f"Incident {incident_id} has no published analysis run",
        )
    run = AnalysisRunRepository(session).get_by_id(run_id)
    if run is None or run.incident_id != incident_id or run.status != "current":
        _api_error(
            http_status.HTTP_409_CONFLICT,
            "STALE_ANALYSIS",
            f"Incident {incident_id} does not point to a valid current analysis run",
            current_analysis_run_id=run_id,
        )
    return incident, run, run_id


def _encode_cursor(row: models.Incident, filters: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "started_at": _utc(row.started_at).isoformat(),
            "incident_id": row.id,
            "filters": filters,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None, filters: dict[str, Any]
) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if payload.get("filters") != filters:
            raise ValueError("cursor filters changed")
        started_at = datetime.fromisoformat(payload["started_at"])
        incident_id = str(payload["incident_id"])
        if not incident_id:
            raise ValueError("empty incident id")
        return _utc(started_at), incident_id
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        _api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "INVALID_CURSOR",
            "Incident cursor is malformed or does not match the active filters",
        )


def _timeline(
    session: Session,
    incident_id: str,
    evidence_rows: list[models.Evidence],
) -> list[TimelineItem]:
    incident_repo = IncidentRepository(session)
    attached = {
        row.event_id: row for row in incident_repo.get_attached_events(incident_id)
    }
    evaluations = {
        row.event_id: row for row in incident_repo.get_all_evaluations(incident_id)
    }
    event_ids = set(attached) | set(evaluations)
    event_rows = EventRepository(session).get_events_by_ids(list(event_ids))
    events_by_id = {row.id: row for row in event_rows}
    if set(events_by_id) != event_ids:
        _api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "Incident timeline contains an unresolved event reference",
        )

    relevance: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for evidence in evidence_rows:
        if evidence.source_event_id in attached:
            relevance[evidence.source_event_id][evidence.hypothesis_id].append(
                evidence.reason_code
            )

    result: list[TimelineItem] = []
    for event_id, event in events_by_id.items():
        if event_id in attached:
            association = attached[event_id]
            decision = "attached"
        else:
            association = evaluations[event_id]
            decision = "excluded"
        result.append(
            TimelineItem(
                event=_event_contract(event),
                attachment_decision=decision,
                attachment_score=association.attachment_score,
                attachment_reasons=list(association.attachment_reasons or []),
                hypothesis_relevance={
                    hypothesis_id: sorted(set(reason_codes))
                    for hypothesis_id, reason_codes in relevance[event_id].items()
                }
                if decision == "attached"
                else {},
            )
        )
    return sorted(result, key=lambda item: (item.event.timestamp, item.event.event_id))


def _topology(
    incident: models.Incident, hypotheses: list[Hypothesis]
) -> TopologySnapshot:
    graph = get_topology_graph()
    top = min(hypotheses, key=lambda item: item.rank, default=None)
    suspected_root = top.candidate_entity_id if top else incident.primary_entity_id
    node_states = {
        entity_id: "impact_path" for entity_id in incident.affected_entity_ids or []
    }
    node_states[incident.primary_entity_id] = "primary_affected"
    node_states[suspected_root] = "suspected_root"
    edge_states: dict[tuple[str, str, str], str] = {}
    for affected_entity_id in incident.affected_entity_ids or []:
        if affected_entity_id == suspected_root:
            continue
        try:
            path = graph.get_traffic_impact_path(suspected_root, affected_entity_id)
        except TopologyPathNotFoundError:
            continue
        for source, target in pairwise(path):
            edge_states[(source, target, TopologyRelation.SENDS_TRAFFIC_TO.value)] = (
                "impact_path"
            )
    return TopologySnapshot.model_validate(
        graph.snapshot(node_states=node_states, edge_states=edge_states)
    )


def _recommendations(
    session: Session, run_id: str, hypothesis_ids: set[str]
) -> dict[str, list[PlaybookRecommendation]]:
    rows = list(
        session.execute(
            select(models.PlaybookRecommendation)
            .where(models.PlaybookRecommendation.analysis_run_id == run_id)
            .order_by(models.PlaybookRecommendation.id.asc())
        ).scalars()
    )
    grouped: dict[str, list[PlaybookRecommendation]] = {
        hypothesis_id: [] for hypothesis_id in hypothesis_ids
    }
    for row in rows:
        if row.hypothesis_id not in hypothesis_ids:
            _api_error(
                http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "Recommendation references a hypothesis outside its analysis run",
            )
        step = get_step(row.step_id)
        if step is None:
            _api_error(
                http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                f"Recommendation references unknown playbook step {row.step_id}",
            )
        grouped[row.hypothesis_id].append(
            PlaybookRecommendation(
                recommendation_id=row.id,
                analysis_run_id=row.analysis_run_id,
                incident_id=row.incident_id,
                hypothesis_id=row.hypothesis_id,
                step_id=row.step_id,
                title=step["title"],
                step_type=step["step_type"],
                risk_level=step["risk_level"],
                requires_human_approval=step["requires_human_approval"],
                instructions="\n".join(step["instructions"]),
                rationale=row.rationale,
            )
        )
    return grouped


def _explanation(
    session: Session,
    run_id: str,
    incident_id: str,
    top_hypothesis_id: str | None,
) -> ExplanationOutput:
    rows = list(
        session.execute(
            select(models.Explanation).where(
                models.Explanation.analysis_run_id == run_id,
                models.Explanation.incident_id == incident_id,
                models.Explanation.validated.is_(True),
            )
        ).scalars()
    )
    if not rows:
        _api_error(
            http_status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            f"No validated explanation exists for analysis run {run_id}",
        )
    preferred = max(
        rows,
        key=lambda row: (row.generator == "llm", _utc(row.created_at), row.id),
    )
    payload = dict(preferred.payload or {})
    payload.setdefault("analysis_run_id", run_id)
    payload.setdefault("incident_id", incident_id)
    payload.setdefault("hypothesis_id", top_hypothesis_id)
    payload.setdefault("generator", preferred.generator)
    try:
        return ExplanationOutput.model_validate(payload)
    except ValueError as exc:
        _api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            f"Stored explanation does not satisfy the API contract: {exc}",
        )


def _snapshot(session: Session, incident_id: str) -> InvestigationResponse:
    incident, analysis_run, run_id = _current_context(session, incident_id)
    hypothesis_rows = HypothesisRepository(session).list_for_run(run_id)
    hypotheses = [_hypothesis_contract(row) for row in hypothesis_rows]
    hypothesis_ids = {item.hypothesis_id for item in hypotheses}
    evidence_rows = EvidenceRepository(session).list_for_run(run_id)
    evidence_by_hypothesis: dict[str, list[EvidenceItem]] = {
        hypothesis_id: [] for hypothesis_id in hypothesis_ids
    }
    for row in evidence_rows:
        if row.hypothesis_id not in hypothesis_ids:
            _api_error(
                http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "Evidence references a hypothesis outside its analysis run",
            )
        evidence_by_hypothesis[row.hypothesis_id].append(_evidence_contract(row))

    timeline = _timeline(session, incident_id, evidence_rows)
    attached_event_ids = {
        item.event.event_id
        for item in timeline
        if item.attachment_decision == "attached"
    }
    if any(
        item.source_event_id is not None and item.source_event_id not in attached_event_ids
        for items in evidence_by_hypothesis.values()
        for item in items
    ):
        _api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "Excluded event was referenced as incident evidence",
        )

    recommendations = _recommendations(session, run_id, hypothesis_ids)
    explanation = _explanation(session, run_id, incident_id, incident.top_hypothesis_id)
    evidence_ids = {
        item.evidence_id
        for items in evidence_by_hypothesis.values()
        for item in items
    }
    if any(
        evidence_id not in evidence_ids
        for claim in explanation.claims
        for evidence_id in claim.evidence_ids
    ):
        _api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "Explanation references evidence outside its analysis snapshot",
        )

    reviews = [
        _review_contract(row)
        for row in ReviewRepository(session).list_for_incident(incident_id)
        if row.analysis_run_id == run_id
    ]
    response = InvestigationResponse(
        generated_at=datetime.now(timezone.utc),
        analysis_run_id=run_id,
        analysis_run=_run_contract(analysis_run),
        incident=_incident_contract(incident),
        timeline=timeline,
        topology=_topology(incident, hypotheses),
        hypotheses=hypotheses,
        evidence_by_hypothesis=evidence_by_hypothesis,
        recommendations_by_hypothesis=recommendations,
        explanation=explanation,
        reviews=reviews,
    )
    response.assert_consistent_run()
    if any(review.analysis_run_id != run_id for review in response.reviews):
        _api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "Review outside the current analysis run entered the snapshot",
        )
    return response


@router.get("", response_model=dict[str, Any])
def list_incidents(
    session: DatabaseSession,
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    primary_entity_id: Annotated[str | None, Query(min_length=1)] = None,
    min_severity: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    filters = {
        "status": status_filter.value if status_filter else None,
        "primary_entity_id": primary_entity_id,
        "min_severity": min_severity,
    }
    before_started_at, before_incident_id = _decode_cursor(cursor, filters)
    rows = IncidentRepository(session).list_page(
        status=filters["status"],
        primary_entity_id=primary_entity_id,
        min_severity=min_severity,
        before_started_at=before_started_at,
        before_incident_id=before_incident_id,
        limit=limit + 1,
    )
    page = rows[:limit]
    return {
        "generated_at": datetime.now(timezone.utc),
        "items": [_incident_contract(row) for row in page],
        "next_cursor": _encode_cursor(page[-1], filters) if len(rows) > limit else None,
    }


@router.get("/{incident_id}/investigation", response_model=InvestigationResponse)
def investigation(incident_id: str, session: DatabaseSession) -> InvestigationResponse:
    return _snapshot(session, incident_id)


@router.get("/{incident_id}/timeline", response_model=list[TimelineItem])
def timeline(incident_id: str, session: DatabaseSession) -> list[TimelineItem]:
    _, _, run_id = _current_context(session, incident_id)
    evidence = EvidenceRepository(session).list_for_run(run_id)
    return _timeline(session, incident_id, evidence)


@router.get("/{incident_id}/hypotheses", response_model=list[Hypothesis])
def hypotheses(incident_id: str, session: DatabaseSession) -> list[Hypothesis]:
    _, _, run_id = _current_context(session, incident_id)
    return [
        _hypothesis_contract(row)
        for row in HypothesisRepository(session).list_for_run(run_id)
    ]


@router.get("/{incident_id}/evidence", response_model=dict[str, list[EvidenceItem]])
def evidence(
    incident_id: str, session: DatabaseSession
) -> dict[str, list[EvidenceItem]]:
    _, _, run_id = _current_context(session, incident_id)
    hypothesis_ids = {
        row.id for row in HypothesisRepository(session).list_for_run(run_id)
    }
    grouped = {hypothesis_id: [] for hypothesis_id in hypothesis_ids}
    for row in EvidenceRepository(session).list_for_run(run_id):
        if row.hypothesis_id not in grouped:
            _api_error(
                http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "Evidence references a hypothesis outside its analysis run",
            )
        grouped[row.hypothesis_id].append(_evidence_contract(row))
    return grouped


@router.get(
    "/{incident_id}/recommendations",
    response_model=dict[str, list[PlaybookRecommendation]],
)
def recommendations(
    incident_id: str, session: DatabaseSession
) -> dict[str, list[PlaybookRecommendation]]:
    _, _, run_id = _current_context(session, incident_id)
    hypothesis_ids = {
        row.id for row in HypothesisRepository(session).list_for_run(run_id)
    }
    return _recommendations(session, run_id, hypothesis_ids)


@router.get("/{incident_id}/explanation", response_model=ExplanationOutput)
def explanation(incident_id: str, session: DatabaseSession) -> ExplanationOutput:
    incident, _, run_id = _current_context(session, incident_id)
    return _explanation(session, run_id, incident_id, incident.top_hypothesis_id)


@router.post("/{incident_id}/recompute", response_model=dict[str, Any])
def recompute(incident_id: str, session: DatabaseSession) -> dict[str, Any]:
    incident = IncidentRepository(session).get_by_id(incident_id)
    if incident is None:
        _api_error(http_status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Incident not found")
    if not orchestrator.status()["analysis_engine_registered"]:
        _api_error(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "ANALYSIS_NOT_READY",
            "The RCA analysis engine is not registered",
        )
    prior_run_id = incident.current_analysis_run_id
    orchestrator.recompute(incident_id, session)
    session.refresh(incident)
    return {
        "request_id": f"req_{uuid.uuid4().hex}",
        "generated_at": datetime.now(timezone.utc),
        "analysis_run_id": incident.current_analysis_run_id,
        "changed": incident.current_analysis_run_id != prior_run_id,
    }


@router.get("/{incident_id}/audit", response_model=list[AuditRecord])
def audit(incident_id: str, session: DatabaseSession) -> list[AuditRecord]:
    if IncidentRepository(session).get_by_id(incident_id) is None:
        _api_error(http_status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Incident not found")
    return audit_service.list_for_incident(incident_id, session)


@router.post("/{incident_id}/review", response_model=ReviewMutationResponse)
def review(
    incident_id: str,
    review_request: ReviewRequest,
    session: DatabaseSession,
) -> ReviewMutationResponse:
    try:
        return review_service.submit(incident_id, review_request, session)
    except ReviewServiceError as exc:
        _api_error(exc.status_code, exc.code, exc.message, **exc.details)


@router.get("/{incident_id}", response_model=IncidentSummary)
def incident_summary(incident_id: str, session: DatabaseSession) -> IncidentSummary:
    row = IncidentRepository(session).get_by_id(incident_id)
    if row is None:
        _api_error(
            http_status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            f"Incident not found: {incident_id}",
        )
    return _incident_contract(row)
