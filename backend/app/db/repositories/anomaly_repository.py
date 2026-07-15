"""
Anomaly repository (Person 1 — blueprint §8.3).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class AnomalyRepository:
    """Anomaly record persistence and retrieval."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def persist(self, row: models.Anomaly) -> models.Anomaly:
        self.session.add(row)
        self.session.flush()
        return row

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, anomaly_id: str) -> models.Anomaly | None:
        return self.session.get(models.Anomaly, anomaly_id)

    def list_by_event(self, event_id: str) -> list[models.Anomaly]:
        stmt = select(models.Anomaly).where(models.Anomaly.event_id == event_id)
        return list(self.session.execute(stmt).scalars())

    def list_by_events(self, event_ids: list[str]) -> list[models.Anomaly]:
        """Return anomalies for an ordered incident-event set in one query."""
        if not event_ids:
            return []
        stmt = (
            select(models.Anomaly)
            .where(models.Anomaly.event_id.in_(event_ids))
            .order_by(models.Anomaly.detected_at.asc(), models.Anomaly.id.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_recent(self, *, limit: int = 20) -> list[models.Anomaly]:
        stmt = (
            select(models.Anomaly)
            .order_by(models.Anomaly.detected_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def list_in_window(
        self,
        window_start: datetime,
        window_end: datetime,
        *,
        can_open_incident: bool | None = None,
    ) -> list[models.Anomaly]:
        """Return anomalies whose window_end falls within the given range."""
        stmt = select(models.Anomaly).where(
            models.Anomaly.window_end >= window_start,
            models.Anomaly.window_end <= window_end,
        )
        if can_open_incident is not None:
            stmt = stmt.where(models.Anomaly.can_open_incident == can_open_incident)
        stmt = stmt.order_by(models.Anomaly.window_end.asc())
        return list(self.session.execute(stmt).scalars())

    def list_for_entity_in_window(
        self,
        entity_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[models.Anomaly]:
        """Return anomalies for a specific entity via join on events."""
        stmt = (
            select(models.Anomaly)
            .join(models.Event, models.Anomaly.event_id == models.Event.id)
            .where(
                models.Event.entity_id == entity_id,
                models.Anomaly.window_end >= window_start,
                models.Anomaly.window_end <= window_end,
            )
            .order_by(models.Anomaly.window_end.asc())
        )
        return list(self.session.execute(stmt).scalars())
