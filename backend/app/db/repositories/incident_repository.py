"""
Incident and AnalysisRun repositories (Person 1 — blueprint §8.3).

Key invariants enforced here:
- At most one AnalysisRun per incident may have status='current'.
- incident_events contains ATTACHED events only.
- incident_event_evaluations records every considered event (attached|excluded).
- Atomic publication: insert children first, then swap current_analysis_run_id.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.db import models


class IncidentRepository:
    """Incident lifecycle and event attachment."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create(self, row: models.Incident) -> models.Incident:
        self.session.add(row)
        self.session.flush()
        return row

    def update_status(self, incident_id: str, status: str) -> None:
        row = self._get_or_raise(incident_id)
        row.status = status
        self.session.flush()

    def update_last_event_at(self, incident_id: str, ts: datetime) -> None:
        row = self._get_or_raise(incident_id)
        if ts > row.last_event_at:
            row.last_event_at = ts
            self.session.flush()

    def set_current_analysis_run(
        self,
        incident_id: str,
        run_id: str,
        top_hypothesis_id: str | None,
    ) -> None:
        """Atomically point incident to a new current run.

        Caller must have already inserted the run, its hypotheses, evidence,
        recommendations, and explanation, and must have marked the prior run
        superseded — all within the same transaction before calling this.
        """
        row = self._get_or_raise(incident_id)
        row.current_analysis_run_id = run_id
        row.top_hypothesis_id = top_hypothesis_id
        row.status = "investigating"
        self.session.flush()

    def set_confirmed_hypothesis(
        self, incident_id: str, hypothesis_id: str
    ) -> None:
        row = self._get_or_raise(incident_id)
        row.confirmed_hypothesis_id = hypothesis_id
        row.status = "resolved"
        self.session.flush()

    def attach_event(self, row: models.IncidentEvent) -> models.IncidentEvent:
        """Record an ATTACHED event (incident_events table)."""
        self.session.add(row)
        self.session.flush()
        return row

    def record_evaluation(
        self, row: models.IncidentEventEvaluation
    ) -> models.IncidentEventEvaluation:
        """Record every considered event (attached OR excluded) in evaluations."""
        self.session.add(row)
        self.session.flush()
        return row

    def increment_anomaly_count(self, incident_id: str) -> None:
        row = self._get_or_raise(incident_id)
        row.anomaly_count += 1
        self.session.flush()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, incident_id: str) -> models.Incident | None:
        return self.session.get(models.Incident, incident_id)

    def _get_or_raise(self, incident_id: str) -> models.Incident:
        row = self.get_by_id(incident_id)
        if row is None:
            raise ValueError(f"Incident not found: {incident_id}")
        return row

    def list_open(self) -> list[models.Incident]:
        stmt = select(models.Incident).where(
            models.Incident.status.in_(["open", "investigating"])
        ).order_by(models.Incident.started_at.desc())
        return list(self.session.execute(stmt).scalars())

    def list_all(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[models.Incident]:
        stmt = select(models.Incident)
        if status:
            stmt = stmt.where(models.Incident.status == status)
        stmt = stmt.order_by(
            models.Incident.started_at.desc(), models.Incident.id.desc()
        ).limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars())

    def list_page(
        self,
        *,
        status: str | None = None,
        primary_entity_id: str | None = None,
        min_severity: float | None = None,
        before_started_at: datetime | None = None,
        before_incident_id: str | None = None,
        limit: int = 50,
    ) -> list[models.Incident]:
        """Return one cursor page ordered by ``(started_at DESC, id DESC)``.

        The API owns opaque cursor encoding; this repository owns incident
        filtering and ordering so feature routes do not duplicate incident SQL.
        """

        stmt = select(models.Incident)
        if status is not None:
            stmt = stmt.where(models.Incident.status == status)
        if primary_entity_id is not None:
            stmt = stmt.where(models.Incident.primary_entity_id == primary_entity_id)
        if min_severity is not None:
            stmt = stmt.where(models.Incident.severity >= min_severity)
        if before_started_at is not None:
            if before_incident_id is None:
                raise ValueError("before_incident_id is required with before_started_at")
            stmt = stmt.where(
                or_(
                    models.Incident.started_at < before_started_at,
                    and_(
                        models.Incident.started_at == before_started_at,
                        models.Incident.id < before_incident_id,
                    ),
                )
            )
        return list(
            self.session.execute(
                stmt.order_by(
                    models.Incident.started_at.desc(), models.Incident.id.desc()
                ).limit(limit)
            ).scalars()
        )

    def get_attached_events(self, incident_id: str) -> list[models.IncidentEvent]:
        stmt = select(models.IncidentEvent).where(
            models.IncidentEvent.incident_id == incident_id
        )
        return list(self.session.execute(stmt).scalars())

    def get_all_evaluations(
        self, incident_id: str
    ) -> list[models.IncidentEventEvaluation]:
        stmt = select(models.IncidentEventEvaluation).where(
            models.IncidentEventEvaluation.incident_id == incident_id
        )
        return list(self.session.execute(stmt).scalars())

    def is_event_attached(self, incident_id: str, event_id: str) -> bool:
        row = self.session.get(models.IncidentEvent, (incident_id, event_id))
        return row is not None

    def find_open_for_entity(
        self,
        entity_id: str,
        within_seconds: int,
        reference_time: datetime,
    ) -> models.Incident | None:
        """Find the most recent open/investigating incident whose last_event_at
        is within within_seconds of reference_time and involves entity_id."""
        from datetime import timedelta
        cutoff = reference_time - timedelta(seconds=within_seconds)
        stmt = (
            select(models.Incident)
            .where(
                models.Incident.status.in_(["open", "investigating"]),
                models.Incident.last_event_at >= cutoff,
            )
            .order_by(models.Incident.last_event_at.desc())
        )
        candidates = list(self.session.execute(stmt).scalars())
        for incident in candidates:
            if entity_id in (incident.affected_entity_ids or []):
                return incident
            if incident.primary_entity_id == entity_id:
                return incident
        return None


class AnalysisRunRepository:
    """Analysis run immutable-snapshot persistence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create(self, row: models.AnalysisRun) -> models.AnalysisRun:
        """Insert a new analysis run with status='building'."""
        self.session.add(row)
        self.session.flush()
        return row

    def mark_current(self, run_id: str) -> None:
        """Transition status building → current.

        The caller must have already marked the prior current run superseded
        (within the same transaction) before calling this.
        """
        row = self._get_or_raise(run_id)
        row.status = "current"
        row.completed_at = datetime.now(tz=__import__("datetime").timezone.utc)
        self.session.flush()

    def supersede(self, run_id: str) -> None:
        """Transition status current → superseded."""
        row = self._get_or_raise(run_id)
        row.status = "superseded"
        self.session.flush()

    def mark_failed(self, run_id: str, reason: str) -> None:
        """Transition status building → failed, recording sanitized reason."""
        row = self._get_or_raise(run_id)
        row.status = "failed"
        row.failure_reason = reason[:2000]  # never store unbounded strings
        self.session.flush()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, run_id: str) -> models.AnalysisRun | None:
        return self.session.get(models.AnalysisRun, run_id)

    def _get_or_raise(self, run_id: str) -> models.AnalysisRun:
        row = self.get_by_id(run_id)
        if row is None:
            raise ValueError(f"AnalysisRun not found: {run_id}")
        return row

    def get_current_for_incident(self, incident_id: str) -> models.AnalysisRun | None:
        stmt = select(models.AnalysisRun).where(
            models.AnalysisRun.incident_id == incident_id,
            models.AnalysisRun.status == "current",
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def fingerprint_exists_as_current(
        self, incident_id: str, fingerprint: str
    ) -> bool:
        """Returns True if the incident's current run already has this fingerprint."""
        current = self.get_current_for_incident(incident_id)
        if current is None:
            return False
        return current.input_fingerprint == fingerprint

    def get_next_revision(self, incident_id: str) -> int:
        """Return the next revision number for this incident."""
        from sqlalchemy import func
        stmt = select(func.max(models.AnalysisRun.revision)).where(
            models.AnalysisRun.incident_id == incident_id
        )
        max_rev = self.session.execute(stmt).scalar_one_or_none()
        return 1 if max_rev is None else max_rev + 1

    def list_for_incident(self, incident_id: str) -> list[models.AnalysisRun]:
        stmt = (
            select(models.AnalysisRun)
            .where(models.AnalysisRun.incident_id == incident_id)
            .order_by(models.AnalysisRun.revision.asc())
        )
        return list(self.session.execute(stmt).scalars())
