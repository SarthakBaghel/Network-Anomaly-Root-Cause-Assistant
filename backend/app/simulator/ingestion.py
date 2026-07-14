from dataclasses import dataclass
from typing import Literal, Protocol

from app.contracts import CanonicalEvent
from app.ingestion.adapters import ADAPTERS
from app.ingestion.adapters.base import AdapterError
from app.db.models import Event
from app.db.session import session_scope
from app.ingestion.pipeline import IngestionPipeline, event_to_contract


@dataclass(frozen=True)
class IngestionOutcome:
    status: Literal["accepted", "collapsed", "quarantined"]
    event: CanonicalEvent | None = None
    reason_code: str | None = None


class IngestionSink(Protocol):
    def ingest(self, source: str, raw: dict) -> IngestionOutcome: ...


class AdapterValidationSink:
    """Phase-1 sink; replace with the Phase-2 persistence pipeline by injection."""

    def __init__(self) -> None:
        self.accepted_events: list[CanonicalEvent] = []

    def ingest(self, source: str, raw: dict) -> IngestionOutcome:
        adapter = ADAPTERS.get(source)
        if adapter is None:
            return IngestionOutcome("quarantined", reason_code="UNKNOWN_SOURCE")
        try:
            event = adapter.adapt(raw)
        except (AdapterError, ValueError) as exc:
            return IngestionOutcome("quarantined", reason_code=getattr(exc, "reason_code", "VALIDATION_ERROR"))
        self.accepted_events.append(event)
        return IngestionOutcome("accepted", event=event)


class PersistentIngestionSink:
    """Runtime sink: simulator records traverse the same pipeline as API records."""

    def ingest(self, source: str, raw: dict) -> IngestionOutcome:
        with session_scope() as session:
            result = IngestionPipeline(session).ingest(source, raw)
            if result.status == "quarantined":
                return IngestionOutcome("quarantined", reason_code=result.reason_codes[0])
            if result.status == "collapsed":
                return IngestionOutcome("collapsed")
            row = session.get(Event, result.event_id) if result.event_id else None
            return IngestionOutcome("accepted", event=event_to_contract(row) if row else None)
