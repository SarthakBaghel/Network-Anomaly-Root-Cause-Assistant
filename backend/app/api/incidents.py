from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any, Literal
import yaml
from pathlib import Path

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
    ReviewDecision,
    ReviewRecord,
    ReviewRequest,
    TimelineItem,
    TopologySnapshot,
    AnalysisRun,
    ExplanationClaim,
    EvidenceCoverage,
)
from app.ingestion.pipeline import event_to_contract
from app.topology.graph import get_topology_graph
from app.api.topology import _incident_annotation

router = APIRouter(prefix="/incidents", tags=["incidents"])

def load_playbook_steps() -> dict[str, dict[str, Any]]:
    yaml_path = Path(__file__).resolve().parents[1] / "fixtures" / "playbooks.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    steps = {}
    for item in data.get("steps", []):
        steps[item["step_id"]] = item
    return steps

def incident_to_summary(row: models.Incident) -> IncidentSummary:
    return IncidentSummary(
        incident_id=row.id,
        title=row.title,
        status=row.status,
        severity=row.severity,
        started_at=row.started_at,
        last_event_at=row.last_event_at,
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
        created_at=row.created_at
    )

@router.get("", response_model=dict[str, Any])
def list_incidents(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session)
) -> dict[str, Any]:
    repo = IncidentRepository(session)
    rows = repo.list_all(status=status, limit=limit, offset=offset)
    return {"items": [incident_to_summary(row) for row in rows]}

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
            instructions=step_meta.get("instructions", ""),
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
def audit(incident_id: str, session: Session = Depends(get_session)) -> list[AuditRecord]:
    repo = IncidentRepository(session)
    row = repo.get_by_id(incident_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}
        )
    stmt = select(models.AuditLog).where(
        models.AuditLog.object_type == "incident",
        models.AuditLog.object_id == incident_id
    ).order_by(models.AuditLog.timestamp.desc())
    rows = session.execute(stmt).scalars().all()
    
    return [
        AuditRecord(
            audit_id=r.id,
            timestamp=r.timestamp,
            actor_type=r.actor_type,
            actor_id=r.actor_id,
            action=r.action,
            object_type=r.object_type,
            object_id=r.object_id,
            request_id=r.payload.get("request_id", ""),
            analysis_run_id=r.payload.get("analysis_run_id"),
            payload=dict(r.payload)
        ) for r in rows
    ]

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
    run_id = orchestrator._run_rca_and_publish(row, trigger_event=None, session=session)
    return {"analysis_run_id": run_id}

@router.post("/{incident_id}/review", response_model=ReviewRecord)
def review(incident_id: str, req: ReviewRequest, session: Session = Depends(get_session)) -> ReviewRecord:
    repo = IncidentRepository(session)
    incident = repo.get_by_id(incident_id)
    if incident is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": f"Incident not found: {incident_id}", "details": []}}
        )
        
    if incident.status in ("resolved", "rejected"):
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "INCIDENT_CLOSED", "message": "Incident is already closed", "details": []}}
        )

    # Check idempotency
    stmt_existing = select(models.Review).where(
        models.Review.incident_id == incident_id,
        models.Review.client_action_id == req.client_action_id
    )
    existing = session.execute(stmt_existing).scalar_one_or_none()
    if existing is not None:
        return ReviewRecord(
            review_id=existing.id,
            incident_id=existing.incident_id,
            analysis_run_id=existing.analysis_run_id,
            hypothesis_id=existing.hypothesis_id,
            decision=existing.decision,
            client_action_id=existing.client_action_id,
            requested_evidence_id=existing.requested_evidence_id,
            reviewer=existing.reviewer,
            comment=existing.comment,
            created_at=existing.created_at
        )

    # Check if hypothesis belongs to the current analysis run
    if not incident.current_analysis_run_id:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "STALE_ANALYSIS", "message": "No current analysis run", "details": []}}
        )
        
    hyp = session.scalar(
        select(models.Hypothesis).where(
            models.Hypothesis.analysis_run_id == incident.current_analysis_run_id,
            models.Hypothesis.id == req.hypothesis_id
        )
    )
    if hyp is None:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "STALE_ANALYSIS",
                    "message": "Stale analysis run",
                    "details": [{"field": "hypothesis_id", "reason_code": "STALE_RUN_ID", "analysis_run_id": incident.current_analysis_run_id}]
                }
            }
        )

    # Check for conflict in terminal decision
    # (Resolved/rejected was already checked above, but let's be double sure if there's any concurrent reviews)
    if req.decision in ("confirm", "reject"):
        pass

    # Save the review
    review_id = f"rev_{uuid.uuid4().hex[:12]}"
    now = datetime.now(tz=timezone.utc)
    review_row = models.Review(
        id=review_id,
        incident_id=incident_id,
        analysis_run_id=incident.current_analysis_run_id,
        hypothesis_id=req.hypothesis_id,
        decision=req.decision.value,
        client_action_id=req.client_action_id,
        requested_evidence_id=req.requested_evidence_id,
        reviewer=req.reviewer,
        comment=req.comment,
        created_at=now
    )
    session.add(review_row)
    
    # Audit trail
    audit_repo = AuditRepository(session)
    
    old_status = incident.status
    if req.decision.value == "confirm":
        incident.confirmed_hypothesis_id = req.hypothesis_id
        incident.status = "resolved"
        
        audit_repo.append(
            audit_id=f"aud_{uuid.uuid4().hex}",
            actor_type="user",
            actor_id=req.reviewer,
            action="REVIEW_CONFIRMED",
            object_type="hypothesis",
            object_id=req.hypothesis_id,
            payload={"incident_id": incident_id, "comment": req.comment}
        )
        audit_repo.append(
            audit_id=f"aud_{uuid.uuid4().hex}",
            actor_type="system",
            actor_id="review_service",
            action="INCIDENT_STATUS_CHANGED",
            object_type="incident",
            object_id=incident_id,
            payload={"previous_status": old_status, "new_status": "resolved"}
        )
    elif req.decision.value == "reject":
        audit_repo.append(
            audit_id=f"aud_{uuid.uuid4().hex}",
            actor_type="user",
            actor_id=req.reviewer,
            action="REVIEW_REJECTED",
            object_type="hypothesis",
            object_id=req.hypothesis_id,
            payload={"incident_id": incident_id, "comment": req.comment}
        )
        
        # Check if all hypotheses in the current run are rejected
        stmt_all_hyps = select(models.Hypothesis).where(models.Hypothesis.analysis_run_id == incident.current_analysis_run_id)
        all_hyps = session.execute(stmt_all_hyps).scalars().all()
        
        stmt_rejected_reviews = select(models.Review).where(
            models.Review.analysis_run_id == incident.current_analysis_run_id,
            models.Review.decision == "reject"
        )
        rejected_hyp_ids = {r.hypothesis_id for r in session.execute(stmt_rejected_reviews).scalars().all()}
        # Add the one currently being rejected
        rejected_hyp_ids.add(req.hypothesis_id)
        
        if all(h.id in rejected_hyp_ids for h in all_hyps):
            incident.status = "rejected"
            audit_repo.append(
                audit_id=f"aud_{uuid.uuid4().hex}",
                actor_type="system",
                actor_id="review_service",
                action="INCIDENT_STATUS_CHANGED",
                object_type="incident",
                object_id=incident_id,
                payload={"previous_status": old_status, "new_status": "rejected"}
            )
    elif req.decision.value == "request_evidence":
        audit_repo.append(
            audit_id=f"aud_{uuid.uuid4().hex}",
            actor_type="user",
            actor_id=req.reviewer,
            action="REVIEW_EVIDENCE_REQUESTED",
            object_type="evidence",
            object_id=req.requested_evidence_id or "",
            payload={"incident_id": incident_id, "comment": req.comment, "hypothesis_id": req.hypothesis_id}
        )
        
    session.flush()
    return ReviewRecord(
        review_id=review_id,
        incident_id=incident_id,
        analysis_run_id=incident.current_analysis_run_id,
        hypothesis_id=req.hypothesis_id,
        decision=req.decision,
        client_action_id=req.client_action_id,
        requested_evidence_id=req.requested_evidence_id,
        reviewer=req.reviewer,
        comment=req.comment,
        created_at=now
    )

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
                hypothesis_relevance={}
            ))
    # Sort chronologically
    timeline_items = sorted(timeline_items, key=lambda it: (it.event.timestamp, it.event.event_id))
    
    # Topology annotated snapshot
    graph = get_topology_graph()
    node_states, edge_states = _incident_annotation(graph, incident_id)
    topology_snap = TopologySnapshot.model_validate(
        graph.snapshot(node_states=node_states, edge_states=edge_states)
    )
    
    # Hypotheses
    stmt_hyps = select(models.Hypothesis).where(models.Hypothesis.analysis_run_id == run_id).order_by(models.Hypothesis.rank.asc())
    hyp_rows = session.execute(stmt_hyps).scalars().all()
    hyps_contract = [hyp_to_contract(r) for r in hyp_rows]
    
    # Evidence grouped
    stmt_ev = select(models.Evidence).where(models.Evidence.analysis_run_id == run_id)
    ev_rows = session.execute(stmt_ev).scalars().all()
    evidence_by_hyp = {}
    for r in ev_rows:
        evidence_by_hyp.setdefault(r.hypothesis_id, []).append(ev_to_contract(r))
        
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
            instructions=step_meta.get("instructions", ""),
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
            created_at=r.created_at
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
        created_at=run_row.created_at,
        completed_at=run_row.completed_at,
        failure_reason=run_row.failure_reason
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
