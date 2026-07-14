from dataclasses import dataclass
from typing import Literal, Protocol

from app.contracts import CanonicalEvent
from app.ingestion.adapters import ADAPTERS
from app.ingestion.adapters.base import AdapterError


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
