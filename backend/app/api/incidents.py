from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Annotated
import base64
import binascii
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from itertools import pairwise
from typing import Annotated, Any, Never

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.db.session import get_session
from app.db.repositories import IncidentRepository, AnalysisRunRepository, AuditRepository
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
    TopologySnapshot,
    AnalysisRun,
    ExplanationClaim,
    EvidenceCoverage,
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
        title=row.title,
        status=row.status,
        severity=row.severity,
        started_at=_to_utc(row.started_at),
        last_event_at=_to_utc(row.last_event_at),
        primary_entity_id=row.primary_entity_id,
        affected_entity_ids=row.affected_entity_ids,
        anomaly_count=row.anomaly_count,
        current_analysis_run_id=row.current_analysis_run_id,
        top_hypothesis_id=row.top_hypothesis_id,
        confirmed_hypothesis_id=row.confirmed_hypothesis_id,
    )

def hyp_to_contract(row: models.Hypothesis) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=row.id,
        analysis_run_id=row.analysis_run_id,
        incident_id=row.incident_id,
        hypothesis_type=row.type,
        candidate_entity_id=row.candidate_entity_id,
        rank=row.rank,
        evidence_score=row.evidence_score,
        evidence_coverage=EvidenceCoverage(
            available=row.coverage["available"],
            expected=row.coverage["expected"]
        ),
        factor_scores=dict(row.factor_scores),
        summary=row.summary
    )

def ev_to_contract(row: models.Evidence) -> EvidenceItem:
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
        created_at=_to_utc(row.created_at)
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
            "started_at": _to_utc(row.started_at).isoformat(),
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
        return _to_utc(started_at), incident_id
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_CURSOR",
                "message": "Incident cursor is malformed or does not match the active filters",
                "details": []
            }
        )

@router.get("", response_model=dict[str, Any])
def list_incidents(
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    primary_entity_id: Annotated[str | None, Query(min_length=1)] = None,
    min_severity: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    filters = {
        "status": status_filter.value if status_filter else None,
        "primary_entity_id": primary_entity_id,
        "min_severity": min_severity,
    }
    before_started_at, before_incident_id = _decode_cursor(cursor, filters)
    repo = IncidentRepository(session)
    rows = repo.list_page(
        status=filters["status"],
        primary_entity_id=primary_entity_id,
        min_severity=min_severity,
        before_started_at=before_started_at,
        before_incident_id=before_incident_id,
        limit=limit + 1,
    )
    page = rows[:limit]
    return {
        "items": [incident_to_summary(row) for row in page],
        "next_cursor": _encode_cursor(page[-1], filters) if len(rows) > limit else None,
    }

@router.get("/{incident_id}", response_model=IncidentSummary)
def incident_summary(incident_id: str, session: Session = Depends(get_session)) -> IncidentSummary:
    repo = IncidentRepository(session)
    row = repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
    return incident_to_summary(row)

@router.get("/{incident_id}/timeline", response_model=dict[str, Any])
def timeline(incident_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = IncidentRepository(session)
    row = repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
    evals = repo.get_all_evaluations(incident_id)
    
    items = []
    for ev_eval in evals:
        evt_row = session.get(models.Event, ev_eval.event_id)
        if evt_row is not None:
            items.append(TimelineItem(
                event=event_to_contract(evt_row),
                attachment_decision=ev_eval.decision,
                attachment_score=ev_eval.attachment_score,
                attachment_reasons=ev_eval.attachment_reasons,
                hypothesis_relevance={}
            ))
    # Sort timeline items chronologically
    items = sorted(items, key=lambda it: (it.event.timestamp, it.event.event_id))
    return {"items": items}

@router.get("/{incident_id}/hypotheses", response_model=list[Hypothesis])
def hypotheses(incident_id: str, session: Session = Depends(get_session)) -> list[Hypothesis]:
    repo = IncidentRepository(session)
    row = repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
    if not row.current_analysis_run_id:
        return []
    stmt = select(models.Hypothesis).where(models.Hypothesis.analysis_run_id == row.current_analysis_run_id).order_by(models.Hypothesis.rank.asc())
    rows = session.execute(stmt).scalars().all()
    return [hyp_to_contract(r) for r in rows]

@router.get("/{incident_id}/evidence", response_model=dict[str, list[EvidenceItem]])
def evidence(incident_id: str, session: Session = Depends(get_session)) -> dict[str, list[EvidenceItem]]:
    repo = IncidentRepository(session)
    row = repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
    if not row.current_analysis_run_id:
        return {}
    stmt = select(models.Evidence).where(models.Evidence.analysis_run_id == row.current_analysis_run_id)
    rows = session.execute(stmt).scalars().all()
    
    result = {}
    for r in rows:
        result.setdefault(r.hypothesis_id, []).append(ev_to_contract(r))
    return result

@router.get("/{incident_id}/recommendations", response_model=dict[str, list[PlaybookRecommendation]])
def recommendations(incident_id: str, session: Session = Depends(get_session)) -> dict[str, list[PlaybookRecommendation]]:
    repo = IncidentRepository(session)
    row = repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
    if not row.current_analysis_run_id:
        return {}
        
    stmt = select(models.PlaybookRecommendation).where(models.PlaybookRecommendation.analysis_run_id == row.current_analysis_run_id)
    rows = session.execute(stmt).scalars().all()
    
    steps = load_playbook_steps()
    result = {}
    for r in rows:
        step_meta = steps.get(r.step_id, {})
        result.setdefault(r.hypothesis_id, []).append(PlaybookRecommendation(
            recommendation_id=r.id,
            analysis_run_id=r.analysis_run_id,
            incident_id=r.incident_id,
            hypothesis_id=r.hypothesis_id,
            step_id=r.step_id,
            title=step_meta.get("title", r.step_id),
            step_type=step_meta.get("step_type", "diagnostic"),
            risk_level=step_meta.get("risk_level", "low"),
            requires_human_approval=step_meta.get("requires_human_approval", True),
            instructions="\n".join(insts) if isinstance(insts := step_meta.get("instructions", ""), list) else insts,
            rationale=r.rationale
        ))
    return result

@router.get("/{incident_id}/explanation", response_model=ExplanationOutput)
def explanation(incident_id: str, session: Session = Depends(get_session)) -> ExplanationOutput:
    repo = IncidentRepository(session)
    row = repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
    if not row.current_analysis_run_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "No current analysis run found for incident", "details": []}
        )
        
    explanation_row = session.scalar(
        select(models.Explanation).where(models.Explanation.analysis_run_id == row.current_analysis_run_id)
    )
    if explanation_row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Explanation not found", "details": []}
        )
        
    top_hyp = session.scalar(
        select(models.Hypothesis).where(models.Hypothesis.analysis_run_id == row.current_analysis_run_id).order_by(models.Hypothesis.rank.asc())
    )
    if top_hyp is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "No hypotheses found", "details": []}
        )
        
    payload = explanation_row.payload
    hyp_payload = next((h for h in payload.get("hypotheses", []) if h["hypothesis_id"] == top_hyp.id), None)
    if hyp_payload is None:
        # Fallback to the first payload entry
        hyp_payload = payload.get("hypotheses", [{}])[0]
        
    claims = [ExplanationClaim(claim=c.get("text", c.get("claim", "")), evidence_ids=c.get("evidence_ids", [])) for c in hyp_payload.get("claims", [])]
    return ExplanationOutput(
        analysis_run_id=row.current_analysis_run_id,
        incident_id=incident_id,
        hypothesis_id=top_hyp.id,
        generator=explanation_row.generator,
        summary=hyp_payload.get("summary", explanation_row.payload.get("incident_summary", "Summary not available")),
        claims=claims,
        diagnostic_step_ids=hyp_payload.get("diagnostic_step_ids", []),
        remediation_step_ids=hyp_payload.get("remediation_step_ids", [])
    )

@router.get("/{incident_id}/audit", response_model=list[AuditRecord])
def audit(incident_id: str, session: DatabaseSession) -> list[AuditRecord]:
    if IncidentRepository(session).get_by_id(incident_id) is None:
        _api_error(http_status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Incident not found")
    return audit_service.list_for_incident(incident_id, session)

@router.post("/{incident_id}/recompute", response_model=dict[str, Any])
def recompute(incident_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    repo = IncidentRepository(session)
    row = repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
    from app.orchestration.orchestrator import orchestrator
    if orchestrator._analysis_engine is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "ANALYSIS_NOT_READY", "message": "Analysis engine is not registered", "details": []}
        )
    run_id = orchestrator._run_rca_and_publish(row, trigger_event=None, session=session)
    return {"analysis_run_id": run_id}

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


@router.get("/{incident_id}/investigation", response_model=InvestigationResponse)
def investigation(incident_id: str, session: Session = Depends(get_session)) -> InvestigationResponse:
    repo = IncidentRepository(session)
    incident_row = repo.get_by_id(incident_id)
    if incident_row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
        
    run_id = incident_row.current_analysis_run_id
    if not run_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "No current analysis run found", "details": []}
        )
        
    run_repo = AnalysisRunRepository(session)
    run_row = run_repo.get_by_id(run_id)
    if run_row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Analysis run not found: {run_id}", "details": []}
        )
        
    # Evidence grouped
    stmt_ev = select(models.Evidence).where(models.Evidence.analysis_run_id == run_id)
    ev_rows = session.execute(stmt_ev).scalars().all()
    evidence_by_hyp = {}
    for r in ev_rows:
        evidence_by_hyp.setdefault(r.hypothesis_id, []).append(ev_to_contract(r))

    from collections import defaultdict
    relevance = defaultdict(lambda: defaultdict(list))
    for r in ev_rows:
        if r.source_event_id:
            relevance[r.source_event_id][r.hypothesis_id].append(r.reason_code)

    # Build timeline
    evals = repo.get_all_evaluations(incident_id)
    timeline_items = []
    for ev_eval in evals:
        evt_row = session.get(models.Event, ev_eval.event_id)
        if evt_row is not None:
            timeline_items.append(TimelineItem(
                event=event_to_contract(evt_row),
                attachment_decision=ev_eval.decision,
                attachment_score=ev_eval.attachment_score,
                attachment_reasons=ev_eval.attachment_reasons,
                hypothesis_relevance={
                    hyp_id: sorted(list(set(reason_codes)))
                    for hyp_id, reason_codes in relevance[ev_eval.event_id].items()
                } if ev_eval.decision == "attached" else {}
            ))
    # Sort chronologically
    timeline_items = sorted(timeline_items, key=lambda it: (it.event.timestamp, it.event.event_id))
    
    # Topology annotated snapshot
    graph = get_topology_graph()
    node_states, edge_states = _incident_annotation(graph, incident_id, session=session)
    topology_snap = TopologySnapshot.model_validate(
        graph.snapshot(node_states=node_states, edge_states=edge_states)
    )
    
    # Hypotheses
    stmt_hyps = select(models.Hypothesis).where(models.Hypothesis.analysis_run_id == run_id).order_by(models.Hypothesis.rank.asc())
    hyp_rows = session.execute(stmt_hyps).scalars().all()
    hyps_contract = [hyp_to_contract(r) for r in hyp_rows]
        
    # Recommendations grouped
    stmt_rec = select(models.PlaybookRecommendation).where(models.PlaybookRecommendation.analysis_run_id == run_id)
    rec_rows = session.execute(stmt_rec).scalars().all()
    recs_by_hyp = {}
    steps = load_playbook_steps()
    for r in rec_rows:
        step_meta = steps.get(r.step_id, {})
        recs_by_hyp.setdefault(r.hypothesis_id, []).append(PlaybookRecommendation(
            recommendation_id=r.id,
            analysis_run_id=r.analysis_run_id,
            incident_id=r.incident_id,
            hypothesis_id=r.hypothesis_id,
            step_id=r.step_id,
            title=step_meta.get("title", r.step_id),
            step_type=step_meta.get("step_type", "diagnostic"),
            risk_level=step_meta.get("risk_level", "low"),
            requires_human_approval=step_meta.get("requires_human_approval", True),
            instructions="\n".join(insts) if isinstance(insts := step_meta.get("instructions", ""), list) else insts,
            rationale=r.rationale
        ))
        
    # Explanation
    explanation_contract = explanation(incident_id, session)
    
    # Reviews
    stmt_rev = select(models.Review).where(models.Review.analysis_run_id == run_id).order_by(models.Review.created_at.asc())
    rev_rows = session.execute(stmt_rev).scalars().all()
    reviews_contract = [
        ReviewRecord(
            review_id=r.id,
            incident_id=r.incident_id,
            analysis_run_id=r.analysis_run_id,
            hypothesis_id=r.hypothesis_id,
            decision=r.decision,
            client_action_id=r.client_action_id,
            requested_evidence_id=r.requested_evidence_id,
            reviewer=r.reviewer,
            comment=r.comment,
            created_at=_to_utc(r.created_at)
        ) for r in rev_rows
    ]
    
    # AnalysisRun
    ar_contract = AnalysisRun(
        analysis_run_id=run_row.id,
        incident_id=run_row.incident_id,
        revision=run_row.revision,
        status=run_row.status,
        trigger_event_id=run_row.trigger_event_id,
        input_fingerprint=run_row.input_fingerprint,
        algorithm_version=run_row.algorithm_version,
        created_at=_to_utc(run_row.created_at),
        completed_at=_to_utc(run_row.completed_at)
    )
    
    return InvestigationResponse(
        generated_at=datetime.now(tz=timezone.utc),
        analysis_run_id=run_id,
        analysis_run=ar_contract,
        incident=incident_to_summary(incident_row),
        timeline=timeline_items,
        topology=topology_snap,
        hypotheses=hyps_contract,
        evidence_by_hypothesis=evidence_by_hyp,
        recommendations_by_hypothesis=recs_by_hyp,
        explanation=explanation_contract,
        reviews=reviews_contract
    )
