from __future__ import annotations

import base64
import binascii
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated, Any, Never

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
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
    TopologySnapshot,
    EvidenceCoverage,
)
from app.db import models
from app.db.repositories import (
    AnalysisRunRepository,
    IncidentRepository,
)
from app.ingestion.pipeline import event_to_contract
from app.orchestration.orchestrator import orchestrator
from app.playbooks.engine import get_step
from app.audit.service import audit_service
from app.reviews.service import ReviewServiceError, review_service
from app.topology.graph import get_topology_graph

from .dependencies import get_session
from .topology import _incident_annotation


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
        started_at=_utc(row.started_at),
        last_event_at=_utc(row.last_event_at),
        primary_entity_id=row.primary_entity_id,
        affected_entity_ids=row.affected_entity_ids,
        anomaly_count=row.anomaly_count,
        current_analysis_run_id=row.current_analysis_run_id,
        top_hypothesis_id=row.top_hypothesis_id,
        confirmed_hypothesis_id=row.confirmed_hypothesis_id,
    )


def load_playbook_steps() -> dict:
    """Load playbook step metadata keyed by step_id from the playbooks engine."""
    from app.playbooks.engine import load_recommendations
    return {rec.step_id: rec.model_dump() for rec in load_recommendations()}


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
        created_at=_utc(row.created_at)
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
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            f"Incident not found: {incident_id}",
        )

    # Read the pointer once. Every child query in this request uses this local
    # immutable value rather than independently selecting a "latest" row.
    run_id = incident.current_analysis_run_id
    if run_id is None:
        _api_error(
            status.HTTP_409_CONFLICT,
            "ANALYSIS_NOT_AVAILABLE",
            f"Incident {incident_id} has no published analysis run",
        )
    run = AnalysisRunRepository(session).get_by_id(run_id)
    if run is None or run.incident_id != incident_id or run.status != "current":
        _api_error(
            status.HTTP_409_CONFLICT,
            "STALE_ANALYSIS",
            f"Incident {incident_id} does not point to a valid current analysis run",
            current_analysis_run_id=run_id,
        )
    return incident, run, run_id


def _timeline_items_for_run(
    session: Session,
    incident_id: str,
    analysis_run_id: str,
) -> list[TimelineItem]:
    """Build an evaluated timeline against one immutable analysis snapshot."""

    relevance: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    evidence_rows = session.execute(
        select(models.Evidence).where(
            models.Evidence.analysis_run_id == analysis_run_id,
            models.Evidence.source_event_id.is_not(None),
        )
    ).scalars()
    for row in evidence_rows:
        relevance[row.source_event_id][row.hypothesis_id].append(row.reason_code)

    items: list[TimelineItem] = []
    for evaluation in IncidentRepository(session).get_all_evaluations(incident_id):
        event_row = session.get(models.Event, evaluation.event_id)
        if event_row is None:
            continue
        hypothesis_relevance = {}
        if evaluation.decision == "attached":
            hypothesis_relevance = {
                hypothesis_id: sorted(set(reason_codes))
                for hypothesis_id, reason_codes in relevance[evaluation.event_id].items()
            }
        items.append(
            TimelineItem(
                event=event_to_contract(event_row),
                attachment_decision=evaluation.decision,
                attachment_score=evaluation.attachment_score,
                attachment_reasons=evaluation.attachment_reasons,
                hypothesis_relevance=hypothesis_relevance,
            )
        )
    return sorted(
        items,
        key=lambda item: (item.event.timestamp, item.event.event_id),
    )


def _explanation_for_run(
    session: Session,
    incident_id: str,
    analysis_run_id: str,
    hypothesis_id: str,
) -> ExplanationOutput:
    """Read the preferred validated explanation without rereading the run pointer."""

    rows = list(
        session.execute(
            select(models.Explanation).where(
                models.Explanation.analysis_run_id == analysis_run_id,
                models.Explanation.incident_id == incident_id,
                models.Explanation.validated.is_(True),
            )
        ).scalars()
    )
    candidates: list[tuple[models.Explanation, ExplanationOutput]] = []
    for row in rows:
        try:
            output = ExplanationOutput.model_validate(row.payload)
        except ValidationError:
            continue
        if (
            output.analysis_run_id == analysis_run_id
            and output.incident_id == incident_id
            and output.hypothesis_id == hypothesis_id
            and output.generator == row.generator
        ):
            candidates.append((row, output))
    if not candidates:
        _api_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "Explanation not found for current analysis run",
        )
    # The publisher always retains the template row and appends a validated LLM
    # row when available. Prefer that optional narration deterministically.
    candidates.sort(
        key=lambda item: (
            item[1].generator == "llm",
            _utc(item[0].created_at),
            item[0].id,
        ),
        reverse=True,
    )
    return candidates[0][1]


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
        "items": [_incident_contract(row) for row in page],
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
    return _incident_contract(row)

@router.get("/{incident_id}/timeline", response_model=dict[str, Any])
def timeline(incident_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    _, _, run_id = _current_context(session, incident_id)
    return {"items": _timeline_items_for_run(session, incident_id, run_id)}

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
    incident_row, _, run_id = _current_context(session, incident_id)
    top_hyp = session.scalar(
        select(models.Hypothesis)
        .where(models.Hypothesis.analysis_run_id == run_id)
        .order_by(models.Hypothesis.rank.asc())
    )
    if top_hyp is None:
        _api_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "No hypotheses found for current analysis run",
        )
    hypothesis_id = incident_row.top_hypothesis_id or top_hyp.id
    return _explanation_for_run(session, incident_id, run_id, hypothesis_id)

@router.get("/{incident_id}/audit", response_model=list[AuditRecord])
def audit(incident_id: str, session: DatabaseSession) -> list[AuditRecord]:
    if IncidentRepository(session).get_by_id(incident_id) is None:
        _api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Incident not found")
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
    if not orchestrator.status()["analysis_engine_registered"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ANALYSIS_NOT_READY",
                "message": "Analysis engine is not registered",
                "details": [],
            },
        )
    run_id = orchestrator.recompute(incident_id, session)
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
    incident_row, run_row, run_id = _current_context(session, incident_id)
    # Freeze the incident envelope before any child query. A concurrent
    # publication may change the database pointer, but this response remains a
    # complete snapshot of the run captured above.
    incident_contract = _incident_contract(incident_row)

    # Evidence grouped
    stmt_ev = select(models.Evidence).where(models.Evidence.analysis_run_id == run_id)
    ev_rows = session.execute(stmt_ev).scalars().all()
    evidence_by_hyp = {}
    for r in ev_rows:
        evidence_by_hyp.setdefault(r.hypothesis_id, []).append(ev_to_contract(r))

    timeline_items = _timeline_items_for_run(session, incident_id, run_id)
    
    # Topology annotated snapshot
    graph = get_topology_graph()
    node_states, edge_states = _incident_annotation(
        graph,
        incident_id,
        session=session,
        analysis_run_id=run_id,
    )
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
        
    top_hypothesis_id = incident_contract.top_hypothesis_id
    if top_hypothesis_id is None and hyp_rows:
        top_hypothesis_id = hyp_rows[0].id
    if top_hypothesis_id is None:
        _api_error(
            status.HTTP_404_NOT_FOUND,
            "NOT_FOUND",
            "No hypotheses found for current analysis run",
        )
    explanation_contract = _explanation_for_run(
        session,
        incident_id,
        run_id,
        top_hypothesis_id,
    )
    
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
            created_at=_utc(r.created_at)
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
        created_at=_utc(run_row.created_at),
        completed_at=_utc(run_row.completed_at)
    )
    
    return InvestigationResponse(
        generated_at=datetime.now(tz=timezone.utc),
        analysis_run_id=run_id,
        analysis_run=ar_contract,
        incident=incident_contract,
        timeline=timeline_items,
        topology=topology_snap,
        hypotheses=hyps_contract,
        evidence_by_hypothesis=evidence_by_hyp,
        recommendations_by_hypothesis=recs_by_hyp,
        explanation=explanation_contract,
        reviews=reviews_contract
    )
