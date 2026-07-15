"""Human review handler (Person 5, blueprint §20.1 and §18.4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.audit.contracts import AuditWrite
from app.audit.service import AuditService, audit_service
from app.contracts import (
    ReviewDecision,
    ReviewMutationResponse,
    ReviewRecord,
    ReviewRequest,
)
from app.db import models
from app.db.repositories import (
    AnalysisRunRepository,
    EvidenceRepository,
    HypothesisRepository,
    IncidentRepository,
    ReviewRepository,
)

from .idempotency import review_request_id


@dataclass(frozen=True)
class ReviewServiceError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ReviewService:
    """Validate and persist one review within the caller's transaction."""

    def __init__(
        self,
        *,
        audit: AuditService = audit_service,
        now: Callable[[], datetime] | None = None,
        review_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.audit = audit
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.review_id_factory = review_id_factory or (
            lambda: f"rev_{uuid.uuid4().hex[:20]}"
        )

    def submit(
        self,
        incident_id: str,
        request: ReviewRequest,
        session: Session,
    ) -> ReviewMutationResponse:
        review_repo = ReviewRepository(session)
        existing = review_repo.get_by_client_action(
            incident_id, request.client_action_id
        )
        if existing is not None:
            return self._mutation_contract(existing)

        incident = IncidentRepository(session).get_by_id(incident_id)
        if incident is None:
            raise ReviewServiceError(404, "NOT_FOUND", "Incident not found")
        if incident.status in {"resolved", "rejected"}:
            raise ReviewServiceError(
                409, "INCIDENT_CLOSED", f"Incident {incident_id} is closed"
            )

        run_id = incident.current_analysis_run_id
        if run_id is None:
            raise ReviewServiceError(
                409,
                "ANALYSIS_NOT_AVAILABLE",
                f"Incident {incident_id} has no published analysis run",
            )
        run = AnalysisRunRepository(session).get_by_id(run_id)
        if (
            request.analysis_run_id != run_id
            or run is None
            or run.incident_id != incident_id
            or run.status != "current"
        ):
            raise self._stale(run_id)

        hypothesis = HypothesisRepository(session).get_by_id(request.hypothesis_id)
        if (
            hypothesis is None
            or hypothesis.incident_id != incident_id
            or hypothesis.analysis_run_id != run_id
        ):
            raise self._stale(run_id)

        terminal = review_repo.get_terminal_for_hypothesis(hypothesis.id, run_id)
        if terminal is not None:
            if terminal.decision == request.decision.value:
                return self._mutation_contract(terminal)
            raise ReviewServiceError(
                409,
                "REVIEW_CONFLICT",
                "Hypothesis already has a conflicting terminal review decision",
            )

        if request.decision is ReviewDecision.EVIDENCE_REQUESTED:
            evidence = EvidenceRepository(session).get_missing_by_id_for_run(
                request.requested_evidence_id or "", run_id
            )
            if evidence is None or evidence.hypothesis_id != hypothesis.id:
                raise ReviewServiceError(
                    422,
                    "VALIDATION_ERROR",
                    "requested_evidence_id must reference missing evidence for this hypothesis",
                    {
                        "requested_evidence_id": (
                            "NOT_MISSING_CURRENT_HYPOTHESIS_EVIDENCE"
                        )
                    },
                )
            prior_request = review_repo.get_evidence_request_for_item(
                run_id, evidence.id
            )
            if prior_request is not None:
                return self._mutation_contract(prior_request)

        now = _utc(self.now())
        row = models.Review(
            id=self.review_id_factory(),
            incident_id=incident_id,
            analysis_run_id=run_id,
            hypothesis_id=hypothesis.id,
            decision=request.decision.value,
            client_action_id=request.client_action_id,
            requested_evidence_id=request.requested_evidence_id,
            reviewer=request.reviewer,
            comment=request.comment,
            created_at=now,
        )
        row, created = review_repo.persist_idempotent(row)
        if not created:
            return self._mutation_contract(row)

        mutation_request_id = review_request_id(
            incident_id, request.client_action_id
        )
        action_by_decision = {
            ReviewDecision.CONFIRMED: "REVIEW_CONFIRMED",
            ReviewDecision.REJECTED: "REVIEW_REJECTED",
            ReviewDecision.EVIDENCE_REQUESTED: "REVIEW_EVIDENCE_REQUESTED",
        }
        self.audit.append(
            AuditWrite(
                action=action_by_decision[request.decision],
                actor_type="user",
                actor_id=request.reviewer,
                object_type="incident",
                object_id=incident_id,
                incident_id=incident_id,
                analysis_run_id=run_id,
                analysis_revision=run.revision,
                request_id=mutation_request_id,
                reason_codes=[request.decision.value.upper()],
                metadata={
                    "hypothesis_id": hypothesis.id,
                    "review_id": row.id,
                    "decision": request.decision.value,
                    "requested_evidence_id": request.requested_evidence_id,
                },
            ),
            session,
            timestamp=now,
        )

        old_status = incident.status
        incident_repo = IncidentRepository(session)
        if request.decision is ReviewDecision.CONFIRMED:
            incident_repo.set_confirmed_hypothesis(incident_id, hypothesis.id)
        elif request.decision is ReviewDecision.REJECTED:
            current_hypotheses = HypothesisRepository(session).list_for_run(run_id)
            if current_hypotheses and all(
                (
                    decision := review_repo.get_terminal_for_hypothesis(
                        item.id, run_id
                    )
                )
                is not None
                and decision.decision == ReviewDecision.REJECTED.value
                for item in current_hypotheses
            ):
                incident_repo.update_status(incident_id, "rejected")

        if incident.status != old_status:
            self.audit.append(
                AuditWrite(
                    action="INCIDENT_STATUS_CHANGED",
                    actor_type="user",
                    actor_id=request.reviewer,
                    object_type="incident",
                    object_id=incident_id,
                    incident_id=incident_id,
                    analysis_run_id=run_id,
                    analysis_revision=run.revision,
                    request_id=mutation_request_id,
                    reason_codes=["HUMAN_REVIEW_STATUS_TRANSITION"],
                    previous_state=old_status,
                    new_state=incident.status,
                    metadata={"review_id": row.id},
                ),
                session,
                timestamp=now,
            )
        return self._mutation_contract(row)

    @staticmethod
    def _stale(current_run_id: str) -> ReviewServiceError:
        return ReviewServiceError(
            409,
            "STALE_ANALYSIS",
            "Review targets a stale analysis run",
            {"current_analysis_run_id": current_run_id},
        )

    @staticmethod
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

    @classmethod
    def _mutation_contract(cls, row: models.Review) -> ReviewMutationResponse:
        return ReviewMutationResponse(
            request_id=review_request_id(row.incident_id, row.client_action_id),
            generated_at=_utc(row.created_at),
            review=cls._review_contract(row),
        )


review_service = ReviewService()
