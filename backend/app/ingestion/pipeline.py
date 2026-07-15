from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import ulid
from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import settings
from app.contracts import CanonicalEvent
from app.db.models import CollapsedEventGroup, Entity, Event, QuarantinedEvent
from app.ingestion.adapters import ADAPTERS
from app.ingestion.adapters.base import AdapterError, SourceAdapter
from app.ingestion.catalogue import log_rule
from app.ingestion.redaction import redact_payload


UTC = timezone.utc
TOPOLOGY_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "topology.json"


class AcceptedEventPublisher(Protocol):
    def publish(self, event: CanonicalEvent) -> None: ...
    def publish_batch(self, events: list[CanonicalEvent]) -> None: ...


class NullPublisher:
    def publish(self, event: CanonicalEvent) -> None:
        del event

    def publish_batch(self, events: list[CanonicalEvent]) -> None:
        del events


@dataclass(frozen=True)
class IngestionResult:
    status: str
    event_id: str | None
    reason_codes: list[str]
    collapsed_group_id: str | None = None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{ulid.new()}"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str).encode()


def duplicate_fingerprint(event: CanonicalEvent) -> str:
    bucket = int(event.timestamp.timestamp()) // settings.duplicate_bucket_seconds
    normalized_signal = event.signal_name or event.event_type
    value = f"{event.entity_id}|{event.modality.value}|{event.event_type}|{normalized_signal}|{bucket}"
    return hashlib.sha256(value.encode()).hexdigest()


def _is_collapsible(event: CanonicalEvent) -> bool:
    if event.modality.value == "alert":
        return True
    if event.modality.value == "log":
        rule = log_rule(event.event_type)
        return bool(rule and rule.get("repeatable"))
    return False


def _to_contract(row: Event) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=row.id,
        timestamp=_utc(row.timestamp),
        ingested_at=_utc(row.ingested_at),
        entity_id=row.entity_id,
        modality=row.modality,
        event_type=row.event_type,
        severity=row.severity,
        signal_name=row.signal_name,
        signal_value=row.signal_value,
        unit=row.unit,
        trace_or_session_id=row.trace_or_session_id,
        source=row.source,
        source_record_id=row.source_record_id,
        schema_version=row.schema_version,
        quality_flags=list(row.quality_flags),
        raw_payload=dict(row.raw_payload),
    )


class IngestionPipeline:
    def __init__(
        self,
        session: Session,
        *,
        publisher: AcceptedEventPublisher | None = None,
        adapters: dict[str, SourceAdapter] | None = None,
    ) -> None:
        self.session = session
        if publisher is None:
            from app.orchestration.publisher import OrchestrationPublisher
            self.publisher: AcceptedEventPublisher = OrchestrationPublisher(session)
        else:
            self.publisher = publisher
        self.adapters = adapters or ADAPTERS

    def ingest(self, source: str, raw: Any, *, publish: bool = True) -> IngestionResult:
        received_at = datetime.now(UTC)
        redacted_raw, raw_was_redacted = redact_payload(raw)
        if len(_json_bytes(raw)) > settings.event_max_payload_bytes:
            return self._quarantine(redacted_raw, received_at, "PAYLOAD_TOO_LARGE")
        if not isinstance(raw, dict):
            return self._quarantine(redacted_raw, received_at, "INVALID_PAYLOAD_TYPE")
        adapter = self.adapters.get(source)
        if adapter is None:
            return self._quarantine(redacted_raw, received_at, "UNKNOWN_SOURCE")
        try:
            event = adapter.adapt(raw)
            event_payload, event_was_redacted = redact_payload(event.raw_payload)
            flags = list(dict.fromkeys(event.quality_flags + (["RAW_PAYLOAD_REDACTED"] if raw_was_redacted or event_was_redacted else [])))
            event = event.model_copy(update={"raw_payload": event_payload, "quality_flags": flags})
            # Revalidate copies so modality rules and datetime boundaries remain enforced.
            event = CanonicalEvent.model_validate(event.model_dump())
        except AdapterError as exc:
            return self._quarantine(redacted_raw, received_at, exc.reason_code, str(exc))
        except ValidationError as exc:
            errors = [{"reason_code": "CANONICAL_VALIDATION_ERROR", "location": list(item["loc"]), "message": item["msg"]} for item in exc.errors()]
            return self._quarantine_errors(redacted_raw, received_at, errors)

        self._ensure_reference_entities()
        if self.session.get(Entity, event.entity_id) is None:
            return self._quarantine(redacted_raw, received_at, "UNKNOWN_ENTITY", event.entity_id)

        existing = self.session.scalar(select(Event).where(Event.source == event.source, Event.source_record_id == event.source_record_id))
        if existing is not None:
            if _to_contract(existing).model_dump(mode="json") == event.model_dump(mode="json"):
                return IngestionResult("idempotent", existing.id, [])
            return self._quarantine(redacted_raw, received_at, "SOURCE_RECORD_CONFLICT")

        fingerprint = duplicate_fingerprint(event)
        if _is_collapsible(event):
            group = self.session.scalar(select(CollapsedEventGroup).where(CollapsedEventGroup.fingerprint == fingerprint))
            representative = self._find_representative(event, fingerprint)
            if representative is not None:
                if group is None:
                    group = CollapsedEventGroup(id=_new_id("ceg"), fingerprint=fingerprint, first_seen=representative.timestamp, last_seen=event.timestamp, event_count=2, representative_event_id=representative.id)
                    self.session.add(group)
                else:
                    group.event_count += 1
                    group.first_seen = min(_utc(group.first_seen), event.timestamp)
                    group.last_seen = max(_utc(group.last_seen), event.timestamp)
                self.session.flush()
                return IngestionResult("collapsed", representative.id, [], group.id)

        row = Event(
            id=event.event_id, timestamp=event.timestamp, ingested_at=event.ingested_at,
            entity_id=event.entity_id, modality=event.modality.value, event_type=event.event_type,
            severity=event.severity, signal_name=event.signal_name, signal_value=event.signal_value,
            unit=event.unit, trace_or_session_id=event.trace_or_session_id, source=event.source,
            source_record_id=event.source_record_id, schema_version=event.schema_version,
            quality_flags=event.quality_flags, raw_payload=event.raw_payload, status="accepted",
        )
        self.session.add(row)
        self.session.flush()
        if publish:
            self.publisher.publish(event)
        return IngestionResult("created", event.event_id, [])

    def ingest_many(self, records: list[tuple[str, Any]]) -> list[IngestionResult]:
        results: list[IngestionResult] = []
        accepted: list[CanonicalEvent] = []
        for source, raw in records:
            result = self.ingest(source, raw, publish=False)
            results.append(result)
            if result.status == "created" and result.event_id:
                row = self.session.get(Event, result.event_id)
                if row is not None:
                    accepted.append(_to_contract(row))
        if accepted:
            self.publisher.publish_batch(accepted)
        return results

    def _find_representative(self, event: CanonicalEvent, fingerprint: str) -> Event | None:
        seconds = settings.duplicate_bucket_seconds
        bucket_start = datetime.fromtimestamp((int(event.timestamp.timestamp()) // seconds) * seconds, UTC)
        query: Select[tuple[Event]] = select(Event).where(
            Event.entity_id == event.entity_id,
            Event.modality == event.modality.value,
            Event.event_type == event.event_type,
            Event.timestamp >= bucket_start,
            Event.timestamp < bucket_start + timedelta(seconds=seconds),
        ).order_by(Event.timestamp, Event.id)
        return next((row for row in self.session.scalars(query) if duplicate_fingerprint(_to_contract(row)) == fingerprint), None)

    def _ensure_reference_entities(self) -> None:
        if self.session.scalar(select(Entity.id).limit(1)) is not None:
            return
        with TOPOLOGY_PATH.open(encoding="utf-8") as handle:
            topology = json.load(handle)
        for node in topology["nodes"]:
            self.session.add(Entity(id=node["id"], name=node["name"], entity_type=node["entity_type"], service=node["service"], criticality=node["criticality"], metadata_json=node.get("metadata", {})))
        self.session.flush()

    def _quarantine(self, raw: Any, received_at: datetime, code: str, message: str | None = None) -> IngestionResult:
        error = {"reason_code": code}
        if message:
            error["message"] = message
        return self._quarantine_errors(raw, received_at, [error])

    def _quarantine_errors(self, raw: Any, received_at: datetime, errors: list[dict[str, Any]]) -> IngestionResult:
        identifier = _new_id("qev")
        self.session.add(QuarantinedEvent(id=identifier, received_at=received_at, raw_payload=raw, validation_errors=errors))
        self.session.flush()
        return IngestionResult("quarantined", None, [str(error["reason_code"]) for error in errors])


event_to_contract = _to_contract
