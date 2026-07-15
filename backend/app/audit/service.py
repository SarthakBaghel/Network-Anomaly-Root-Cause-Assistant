"""Append-only audit trail service (Person 5, blueprint §20.3)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.contracts import AuditRecord
from app.db import models
from app.db.repositories import AuditRepository

from .contracts import AuditWrite


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AuditService:
    """Validate and append audit rows without owning the caller's transaction.

    This service intentionally exposes no update or delete operation.
    """

    def append(
        self,
        write: AuditWrite,
        session: Session,
        *,
        timestamp: datetime | None = None,
        audit_id: str | None = None,
    ) -> models.AuditLog:
        return AuditRepository(session).append_write(
            audit_id=audit_id or f"aud_{uuid.uuid4().hex}",
            write=write,
            timestamp=timestamp,
        )

    def list_for_incident(
        self, incident_id: str, session: Session, *, limit: int = 200
    ) -> list[AuditRecord]:
        return [
            self.to_contract(row)
            for row in AuditRepository(session).list_for_incident(
                incident_id, limit=limit
            )
        ]

    @staticmethod
    def to_contract(row: models.AuditLog) -> AuditRecord:
        payload = dict(row.payload or {})
        return AuditRecord(
            audit_id=row.id,
            timestamp=_utc(row.timestamp),
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            object_type=row.object_type,
            object_id=row.object_id,
            request_id=str(payload.get("request_id", row.id)),
            analysis_run_id=payload.get("analysis_run_id"),
            payload=payload,
        )


audit_service = AuditService()
