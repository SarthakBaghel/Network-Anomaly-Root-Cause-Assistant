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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


# All valid action codes — enforced at the service boundary.
AUDIT_ACTION_CODES = frozenset(
    {
        "EVENT_QUARANTINED",
        "EVENT_COLLAPSED",
        "ANOMALY_DETECTED",
        "INCIDENT_OPENED",
        "EVENT_ATTACHED",
        "EVENT_EXCLUDED",
        "ANALYSIS_PUBLISHED",
        "PIPELINE_STAGE_FAILED",
        "EXPLANATION_FALLBACK_USED",
        "REVIEW_CONFIRMED",
        "REVIEW_REJECTED",
        "REVIEW_EVIDENCE_REQUESTED",
        "INCIDENT_STATUS_CHANGED",
        "DEMO_RESET",
    }
)


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
                f"Unknown audit action code '{action}'. "
                f"Valid codes: {sorted(AUDIT_ACTION_CODES)}"
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
            .order_by(models.AuditLog.timestamp.asc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def list_for_incident(
        self, incident_id: str, *, limit: int = 200
    ) -> list[models.AuditLog]:
        """Return all audit entries that reference a given incident_id."""
        stmt = (
            select(models.AuditLog)
            .where(models.AuditLog.object_id == incident_id)
            .order_by(models.AuditLog.timestamp.asc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def list_recent(self, *, limit: int = 100) -> list[models.AuditLog]:
        stmt = (
            select(models.AuditLog)
            .order_by(models.AuditLog.timestamp.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())
