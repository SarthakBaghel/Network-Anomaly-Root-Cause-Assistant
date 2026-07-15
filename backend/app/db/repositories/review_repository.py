"""
Review repository (Person 1 — blueprint §8.3).

Reviews are append-only. The unique constraint on (incident_id, client_action_id)
enforces idempotency at the DB level; the service layer checks before inserting.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import models


class ReviewRepository:
    """Review persistence and retrieval."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def persist(self, row: models.Review) -> models.Review:
        self.session.add(row)
        self.session.flush()
        return row

    def persist_idempotent(self, row: models.Review) -> tuple[models.Review, bool]:
        """Insert once, handling a concurrent client-action uniqueness race.

        A racing uniqueness failure rolls back the read-only pre-insert
        transaction, then reloads the winning row in a fresh transaction.
        Successful inserts remain in the caller's outer transaction so a later
        audit or lifecycle failure rolls the review back too.
        """

        existing = self.get_by_client_action(row.incident_id, row.client_action_id)
        if existing is not None:
            return existing, False
        try:
            self.session.add(row)
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            existing = self.get_by_client_action(row.incident_id, row.client_action_id)
            if existing is None:
                raise
            return existing, False
        return row, True

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, review_id: str) -> models.Review | None:
        return self.session.get(models.Review, review_id)

    def get_by_client_action(self, incident_id: str, client_action_id: str) -> models.Review | None:
        """Idempotency check: return existing review for the same client_action_id."""
        stmt = select(models.Review).where(
            models.Review.incident_id == incident_id,
            models.Review.client_action_id == client_action_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_for_incident(self, incident_id: str) -> list[models.Review]:
        stmt = (
            select(models.Review)
            .where(models.Review.incident_id == incident_id)
            .order_by(models.Review.created_at.asc(), models.Review.id.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def get_terminal_for_hypothesis(
        self, hypothesis_id: str, analysis_run_id: str
    ) -> models.Review | None:
        """Return an existing confirmed/rejected review for this hypothesis in this run.

        Used to detect REVIEW_CONFLICT (second conflicting terminal decision).
        """
        stmt = select(models.Review).where(
            models.Review.hypothesis_id == hypothesis_id,
            models.Review.analysis_run_id == analysis_run_id,
            models.Review.decision.in_(["confirmed", "rejected"]),
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_evidence_request_for_item(
        self, analysis_run_id: str, evidence_id: str
    ) -> models.Review | None:
        """Return the one allowed evidence request for an item in a run."""

        stmt = select(models.Review).where(
            models.Review.analysis_run_id == analysis_run_id,
            models.Review.decision == "evidence_requested",
            models.Review.requested_evidence_id == evidence_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()
