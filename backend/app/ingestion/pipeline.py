"""Minimal persistent ingestion boundary required by the Phase-3 audit handoff.

Person 3 can extend this module with batch recomputation and detector integration;
the accepted/collapsed/quarantined outcomes and audit fields are frozen here.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.audit.contracts import AuditWrite
from app.audit.service import audit_service
from app.config import settings
from app.contracts import CanonicalEvent, IngestionMutationResponse
from app.db import models
from app.db.repositories import EventRepository
from app.ingestion.adapters import ADAPTERS
from app.ingestion.adapters.base import AdapterError


_SENSITIVE_KEY = re.compile(
    r"password|passwd|token|secret|api_key|authorization", re.IGNORECASE
)
_LOG_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "reference_profiles"
    / "log_templates.yaml"
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _redact(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        changed = False
        for key, item in value.items():
            if _SENSITIVE_KEY.search(str(key)):
                redacted[key] = "[REDACTED]"
                changed = True
            else:
                redacted[key], item_changed = _redact(item)
                changed = changed or item_changed
        return redacted, changed
    if isinstance(value, list):
        output: list[Any] = []
        changed = False
        for item in value:
            clean, item_changed = _redact(item)
            output.append(clean)
            changed = changed or item_changed
        return output, changed
    return value, False


def _source_record_id(raw: dict[str, Any]) -> str | None:
    payload = raw.get("payload", raw)
    if not isinstance(payload, dict):
        return None
    for key in ("sample_id", "record_id", "fingerprint", "change_id"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _repeatable_log_codes() -> frozenset[str]:
    catalogue = yaml.safe_load(_LOG_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return frozenset(
        row["event_code"]
        for row in catalogue.get("templates", [])
        if row.get("repeatable") is True
    )


_REPEATABLE_LOG_CODES = _repeatable_log_codes()


def _is_collapsible(event: CanonicalEvent) -> bool:
    return event.modality.value == "alert" or (
        event.modality.value == "log" and event.event_type in _REPEATABLE_LOG_CODES
    )


def _duplicate_fingerprint(event: CanonicalEvent) -> str:
    timestamp = int(_utc(event.timestamp).timestamp())
    bucket = timestamp // settings.duplicate_bucket_seconds
    normalized_signal = event.signal_name or ""
    material = "|".join(
        (
            event.entity_id,
            event.modality.value,
            event.event_type,
            normalized_signal,
            str(bucket),
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _event_row(event: CanonicalEvent) -> models.Event:
    return models.Event(
        id=event.event_id,
        timestamp=_utc(event.timestamp),
        ingested_at=_utc(event.ingested_at),
        entity_id=event.entity_id,
        modality=event.modality.value,
        event_type=event.event_type,
        severity=event.severity,
        signal_name=event.signal_name,
        signal_value=event.signal_value,
        unit=event.unit,
        trace_or_session_id=event.trace_or_session_id,
        source=event.source,
        source_record_id=event.source_record_id,
        schema_version=event.schema_version,
        quality_flags=list(event.quality_flags),
        raw_payload=dict(event.raw_payload),
        status="accepted",
    )


def event_to_contract(row: models.Event) -> CanonicalEvent:
    """Convert a persisted Event ORM row back to a CanonicalEvent contract.

    Required by simulator/ingestion.py PersistentIngestionSink so it can
    return the accepted CanonicalEvent after pipeline persistence.
    """
    from app.contracts import Modality  # local to avoid circulars at module level

    return CanonicalEvent(
        event_id=row.id,
        timestamp=row.timestamp if row.timestamp.tzinfo else row.timestamp.replace(tzinfo=timezone.utc),
        ingested_at=row.ingested_at if row.ingested_at.tzinfo else row.ingested_at.replace(tzinfo=timezone.utc),
        entity_id=row.entity_id,
        modality=Modality(row.modality),
        event_type=row.event_type,
        severity=row.severity or 0.0,
        signal_name=row.signal_name,
        signal_value=row.signal_value,
        unit=row.unit,
        trace_or_session_id=row.trace_or_session_id,
        source=row.source,
        source_record_id=row.source_record_id,
        schema_version=row.schema_version or "1.0",
        quality_flags=list(row.quality_flags or []),
        raw_payload=dict(row.raw_payload or {}),
    )


class IngestionPipeline:
    """Adapt, validate and persist one source-specific record without committing."""

    def ingest(
        self,
        *,
        source: str,
        raw: dict[str, Any],
        request_id: str,
        session: Session,
    ) -> IngestionMutationResponse:
        now = datetime.now(timezone.utc)
        clean_raw, _ = _redact(raw)
        encoded_size = len(
            json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str).encode()
        )
        adapter = ADAPTERS.get(source)
        if adapter is None:
            return self._quarantine(
                source=source,
                raw=clean_raw,
                source_record_id=_source_record_id(raw),
                request_id=request_id,
                reason_codes=["UNKNOWN_SOURCE"],
                now=now,
                session=session,
            )
        if encoded_size > settings.event_max_payload_bytes:
            return self._quarantine(
                source=source,
                raw=clean_raw,
                source_record_id=_source_record_id(raw),
                request_id=request_id,
                reason_codes=["PAYLOAD_TOO_LARGE"],
                now=now,
                session=session,
            )
        try:
            event = adapter.adapt(raw)
        except (AdapterError, ValueError) as exc:
            return self._quarantine(
                source=source,
                raw=clean_raw,
                source_record_id=_source_record_id(raw),
                request_id=request_id,
                reason_codes=[getattr(exc, "reason_code", "VALIDATION_ERROR")],
                now=now,
                session=session,
            )

        if session.get(models.Entity, event.entity_id) is None:
            return self._quarantine(
                source=source,
                raw=clean_raw,
                source_record_id=event.source_record_id,
                request_id=request_id,
                reason_codes=["UNKNOWN_ENTITY"],
                now=now,
                session=session,
            )

        clean_payload, changed = _redact(event.raw_payload)
        quality_flags = list(event.quality_flags)
        if changed and "RAW_PAYLOAD_REDACTED" not in quality_flags:
            quality_flags.append("RAW_PAYLOAD_REDACTED")
        event = event.model_copy(
            update={"raw_payload": clean_payload, "quality_flags": quality_flags}
        )

        repo = EventRepository(session)
        if event.source_record_id is not None:
            existing = repo.get_by_source_record(event.source, event.source_record_id)
            if existing is not None:
                return IngestionMutationResponse(
                    status="accepted",
                    request_id=request_id,
                    generated_at=now,
                    event_id=existing.id,
                    source_record_id=existing.source_record_id,
                    reason_codes=["IDEMPOTENT_RETRY"],
                    analysis_state="not_started",
                )

        fingerprint = _duplicate_fingerprint(event)
        if _is_collapsible(event):
            group = repo.get_collapsed_group_by_fingerprint(fingerprint)
            if group is not None:
                repo.increment_collapsed_group(group.id, _utc(event.timestamp))
                audit_service.append(
                    AuditWrite(
                        action="EVENT_COLLAPSED",
                        actor_type="system",
                        actor_id="ingestion_pipeline",
                        object_type="collapsed_event_group",
                        object_id=group.id,
                        request_id=request_id,
                        reason_codes=["DUPLICATE_FINGERPRINT"],
                        metadata={
                            "collapsed_group_id": group.id,
                            "representative_event_id": group.representative_event_id,
                            "source": source,
                            "source_record_id": event.source_record_id,
                        },
                    ),
                    session,
                    timestamp=now,
                )
                return IngestionMutationResponse(
                    status="collapsed",
                    request_id=request_id,
                    generated_at=now,
                    collapsed_group_id=group.id,
                    representative_event_id=group.representative_event_id,
                    source_record_id=event.source_record_id,
                    reason_codes=["DUPLICATE_FINGERPRINT"],
                    analysis_state="not_started",
                )

        repo.persist_accepted(_event_row(event))
        if _is_collapsible(event):
            repo.persist_collapsed_group(
                models.CollapsedEventGroup(
                    id=f"col_{uuid.uuid4().hex[:20]}",
                    fingerprint=fingerprint,
                    first_seen=_utc(event.timestamp),
                    last_seen=_utc(event.timestamp),
                    event_count=1,
                    representative_event_id=event.event_id,
                )
            )
        return IngestionMutationResponse(
            status="accepted",
            request_id=request_id,
            generated_at=now,
            event_id=event.event_id,
            source_record_id=event.source_record_id,
            analysis_state="not_started",
        )

    def _quarantine(
        self,
        *,
        source: str,
        raw: dict[str, Any],
        source_record_id: str | None,
        request_id: str,
        reason_codes: list[str],
        now: datetime,
        session: Session,
    ) -> IngestionMutationResponse:
        quarantine_id = f"qevt_{uuid.uuid4().hex[:20]}"
        EventRepository(session).persist_quarantined(
            models.QuarantinedEvent(
                id=quarantine_id,
                received_at=now,
                raw_payload=raw,
                validation_errors=[{"reason_code": code} for code in reason_codes],
            )
        )
        audit_service.append(
            AuditWrite(
                action="EVENT_QUARANTINED",
                actor_type="system",
                actor_id="ingestion_pipeline",
                object_type="quarantined_event",
                object_id=quarantine_id,
                request_id=request_id,
                reason_codes=reason_codes,
                metadata={
                    "quarantine_id": quarantine_id,
                    "source": source,
                    "source_record_id": source_record_id,
                },
            ),
            session,
            timestamp=now,
        )
        return IngestionMutationResponse(
            status="quarantined",
            request_id=request_id,
            generated_at=now,
            quarantine_id=quarantine_id,
            source_record_id=source_record_id,
            reason_codes=reason_codes,
            analysis_state="not_started",
        )


ingestion_pipeline = IngestionPipeline()
