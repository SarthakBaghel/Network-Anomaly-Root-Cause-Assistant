"""
Hypothesis and Evidence repositories (Person 1 — blueprint §8.3).

Both are append-only within a demo run (blueprint §8.2).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class HypothesisRepository:
    """Hypothesis persistence and retrieval (append-only)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def persist(self, row: models.Hypothesis) -> models.Hypothesis:
        self.session.add(row)
        self.session.flush()
        return row

    def persist_many(self, rows: list[models.Hypothesis]) -> list[models.Hypothesis]:
        for row in rows:
            self.session.add(row)
        self.session.flush()
        return rows

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, hypothesis_id: str) -> models.Hypothesis | None:
        return self.session.get(models.Hypothesis, hypothesis_id)

    def list_for_run(self, analysis_run_id: str) -> list[models.Hypothesis]:
        stmt = (
            select(models.Hypothesis)
            .where(models.Hypothesis.analysis_run_id == analysis_run_id)
            .order_by(models.Hypothesis.rank.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_for_incident(self, incident_id: str) -> list[models.Hypothesis]:
        stmt = (
            select(models.Hypothesis)
            .where(models.Hypothesis.incident_id == incident_id)
            .order_by(models.Hypothesis.rank.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def get_top_for_run(self, analysis_run_id: str) -> models.Hypothesis | None:
        stmt = (
            select(models.Hypothesis)
            .where(models.Hypothesis.analysis_run_id == analysis_run_id)
            .order_by(models.Hypothesis.rank.asc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()


class EvidenceRepository:
    """Evidence persistence and retrieval (append-only)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def persist(self, row: models.Evidence) -> models.Evidence:
        self.session.add(row)
        self.session.flush()
        return row

    def persist_many(self, rows: list[models.Evidence]) -> list[models.Evidence]:
        for row in rows:
            self.session.add(row)
        self.session.flush()
        return rows

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, evidence_id: str) -> models.Evidence | None:
        return self.session.get(models.Evidence, evidence_id)

    def list_for_hypothesis(self, hypothesis_id: str) -> list[models.Evidence]:
        stmt = (
            select(models.Evidence)
            .where(models.Evidence.hypothesis_id == hypothesis_id)
            .order_by(models.Evidence.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_for_run(self, analysis_run_id: str) -> list[models.Evidence]:
        stmt = (
            select(models.Evidence)
            .where(models.Evidence.analysis_run_id == analysis_run_id)
            .order_by(models.Evidence.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_missing_for_hypothesis(self, hypothesis_id: str) -> list[models.Evidence]:
        """Return missing-evidence items (source_event_id IS NULL)."""
        stmt = (
            select(models.Evidence)
            .where(
                models.Evidence.hypothesis_id == hypothesis_id,
                models.Evidence.kind == "missing",
            )
        )
        return list(self.session.execute(stmt).scalars())

    def get_missing_by_id_for_run(
        self, evidence_id: str, analysis_run_id: str
    ) -> models.Evidence | None:
        """Validate that a missing-evidence item belongs to the given run (for reviews)."""
        stmt = select(models.Evidence).where(
            models.Evidence.id == evidence_id,
            models.Evidence.analysis_run_id == analysis_run_id,
            models.Evidence.kind == "missing",
        )
        return self.session.execute(stmt).scalar_one_or_none()
