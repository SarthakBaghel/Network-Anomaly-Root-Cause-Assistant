"""
Event and Quarantine repositories (Person 1 — blueprint §8.3).

All SQL stays here. Feature modules call these interfaces; they do not write
SQL directly. Only the reset service may bulk-delete via its own path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


class EventRepository:
    """Accepted canonical event persistence and retrieval."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def persist_accepted(self, row: models.Event) -> models.Event:
        """Persist a new accepted Event row. Caller must have built the ORM
        object; the repository only adds and flushes it."""
        self.session.add(row)
        self.session.flush()
        return row

    def persist_quarantined(self, row: models.QuarantinedEvent) -> models.QuarantinedEvent:
        self.session.add(row)
        self.session.flush()
        return row

    def persist_collapsed_group(
        self, row: models.CollapsedEventGroup
    ) -> models.CollapsedEventGroup:
        self.session.add(row)
        self.session.flush()
        return row

    def increment_collapsed_group(self, group_id: str, last_seen: datetime) -> None:
        """Increment event_count and update last_seen for a collapsed group."""
        row = self.session.get(models.CollapsedEventGroup, group_id)
        if row:
            row.event_count += 1
            row.last_seen = last_seen
            self.session.flush()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, event_id: str) -> models.Event | None:
        return self.session.get(models.Event, event_id)

    def get_by_source_record(
        self, source: str, source_record_id: str
    ) -> models.Event | None:
        stmt = select(models.Event).where(
            models.Event.source == source,
            models.Event.source_record_id == source_record_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_collapsed_group_by_fingerprint(
        self, fingerprint: str
    ) -> models.CollapsedEventGroup | None:
        stmt = select(models.CollapsedEventGroup).where(
            models.CollapsedEventGroup.fingerprint == fingerprint
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_events(
        self,
        *,
        limit: int = 50,
        cursor_timestamp: datetime | None = None,
        cursor_id: str | None = None,
        modality: str | None = None,
        entity_id: str | None = None,
    ) -> list[models.Event]:
        """Cursor-based list: (timestamp DESC, id DESC)."""
        stmt = select(models.Event)
        if modality:
            stmt = stmt.where(models.Event.modality == modality)
        if entity_id:
            stmt = stmt.where(models.Event.entity_id == entity_id)
        if cursor_timestamp and cursor_id:
            stmt = stmt.where(
                (models.Event.timestamp < cursor_timestamp)
                | (
                    (models.Event.timestamp == cursor_timestamp)
                    & (models.Event.id < cursor_id)
                )
            )
        stmt = stmt.order_by(models.Event.timestamp.desc(), models.Event.id.desc())
        stmt = stmt.limit(limit)
        return list(self.session.execute(stmt).scalars())

    def list_quarantined(self, *, limit: int = 50) -> list[models.QuarantinedEvent]:
        stmt = (
            select(models.QuarantinedEvent)
            .order_by(models.QuarantinedEvent.received_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def get_events_in_window(
        self,
        entity_id: str,
        modality: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[models.Event]:
        """Used by detectors to fetch baseline/window data."""
        stmt = (
            select(models.Event)
            .where(
                models.Event.entity_id == entity_id,
                models.Event.modality == modality,
                models.Event.timestamp >= window_start,
                models.Event.timestamp <= window_end,
            )
            .order_by(models.Event.timestamp.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_accepted_in_window(
        self,
        window_start: datetime,
        window_end: datetime,
        *,
        end_inclusive: bool = True,
    ) -> list[models.Event]:
        """Return accepted events across every entity and modality.

        Incident lookback uses an exclusive end so records sharing the opening
        timestamp are handled in committed ingestion order rather than being
        pulled into the incident before their own pipeline turn.
        """

        end_predicate = (
            models.Event.timestamp <= window_end
            if end_inclusive
            else models.Event.timestamp < window_end
        )
        stmt = (
            select(models.Event)
            .where(
                models.Event.status == "accepted",
                models.Event.timestamp >= window_start,
                end_predicate,
            )
            .order_by(models.Event.timestamp.asc(), models.Event.id.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def get_events_by_ids(self, event_ids: list[str]) -> list[models.Event]:
        if not event_ids:
            return []
        stmt = select(models.Event).where(models.Event.id.in_(event_ids))
        return list(self.session.execute(stmt).scalars())

    def count_per_source(self) -> dict[str, dict[str, int]]:
        """Returns per-source counts: accepted, quarantined (no collapsed yet)."""
        from sqlalchemy import func
        stmt = select(models.Event.source, func.count()).group_by(models.Event.source)
        rows = self.session.execute(stmt).all()
        return {source: {"accepted": count} for source, count in rows}
