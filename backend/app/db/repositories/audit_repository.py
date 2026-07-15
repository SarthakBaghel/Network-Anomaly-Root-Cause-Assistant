"""
Audit log repository (Person 1 — blueprint §8.3, §20.3).

Audit logs are strictly append-only. There is no update or delete path
other than the reset service bulk purge. Every audit entry must carry
IDs, reason codes, and state information — never secrets or raw payloads.

Frozen action codes (blueprint §20.3):
  EVENT_QUARANTINED, EVENT_COLLAPSED, ANOMALY_DETECTED, INCIDENT_OPENED,
  EVENT_ATTACHED, EVENT_EXCLUDED, ANALYSIS_PUBLISHED, PIPELINE_STAGE_FAILED,
  EXPLANATION_FALLBACK_USED, REVIEW_CONFIRMED, REVIEW_REJECTED,
  REVIEW_EVIDENCE_REQUESTED, INCIDENT_STATUS_CHANGED, DEMO_RESET
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db import models
from app.audit.contracts import AUDIT_ACTION_CODES, AuditWrite


class AuditRepository:
    """Append-only audit log."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def append(
        self,
        *,
        audit_id: str,
        actor_type: str,
        actor_id: str | None,
        action: str,
        object_type: str,
        object_id: str,
        payload: dict[str, Any],
        timestamp: datetime | None = None,
    ) -> models.AuditLog:
        """Append one audit entry. Raises ValueError for unknown action codes."""
        if action not in AUDIT_ACTION_CODES:
            raise ValueError(
                f"Unknown audit action code '{action}'. Valid codes: {sorted(AUDIT_ACTION_CODES)}"
            )
        ts = timestamp or datetime.now(tz=timezone.utc)
        row = models.AuditLog(
            id=audit_id,
            timestamp=ts,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            payload=payload,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def append_write(
        self,
        *,
        audit_id: str,
        write: AuditWrite,
        timestamp: datetime | None = None,
    ) -> models.AuditLog:
        """Persist the validated boundary without exposing raw payload assembly."""

        return self.append(
            audit_id=audit_id,
            actor_type=write.actor_type.value,
            actor_id=write.actor_id,
            action=write.action,
            object_type=write.object_type,
            object_id=write.object_id,
            payload=write.payload(),
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_id(self, audit_id: str) -> models.AuditLog | None:
        return self.session.get(models.AuditLog, audit_id)

    def list_for_object(
        self,
        object_type: str,
        object_id: str,
        *,
        limit: int = 200,
    ) -> list[models.AuditLog]:
        stmt = (
            select(models.AuditLog)
            .where(
                models.AuditLog.object_type == object_type,
                models.AuditLog.object_id == object_id,
            )
            .order_by(models.AuditLog.timestamp.desc(), models.AuditLog.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def list_for_incident(
        self,
        incident_id: str,
        *,
        limit: int = 200,
        before_timestamp: datetime | None = None,
        before_audit_id: str | None = None,
    ) -> list[models.AuditLog]:
        """Return incident-owned and event-owned entries for one incident."""
        conditions = [
            or_(
                models.AuditLog.object_id == incident_id,
                models.AuditLog.payload["incident_id"].as_string() == incident_id,
            )
        ]
        if before_timestamp is not None and before_audit_id is not None:
            conditions.append(
                or_(
                    models.AuditLog.timestamp < before_timestamp,
                    and_(
                        models.AuditLog.timestamp == before_timestamp,
                        models.AuditLog.id < before_audit_id,
                    ),
                )
            )
        stmt = (
            select(models.AuditLog)
            .where(*conditions)
            .order_by(models.AuditLog.timestamp.desc(), models.AuditLog.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def list_recent(self, *, limit: int = 100) -> list[models.AuditLog]:
        stmt = (
            select(models.AuditLog)
            .order_by(models.AuditLog.timestamp.desc(), models.AuditLog.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())
