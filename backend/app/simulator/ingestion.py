from dataclasses import dataclass
import hashlib
import json
from typing import Literal, Protocol, Sequence

from app.contracts import CanonicalEvent
from app.ingestion.adapters import ADAPTERS
from app.ingestion.adapters.base import AdapterError
from app.db.models import Event
from app.db.session import session_scope
from app.ingestion.pipeline import IngestionPipeline, event_to_contract
from app.ingestion.runtime_label_guard import contains_forbidden_label


@dataclass(frozen=True)
class IngestionOutcome:
    status: Literal["accepted", "collapsed", "quarantined"]
    event: CanonicalEvent | None = None
    reason_code: str | None = None


class IngestionSink(Protocol):
    def ingest(self, source: str, raw: dict) -> IngestionOutcome: ...

    def ingest_group(self, records: Sequence[tuple[str, dict]]) -> list[IngestionOutcome]: ...


class AdapterValidationSink:
    """Phase-1 sink; replace with the Phase-2 persistence pipeline by injection."""

    def __init__(self) -> None:
        self.accepted_events: list[CanonicalEvent] = []

    def ingest(self, source: str, raw: dict) -> IngestionOutcome:
        if contains_forbidden_label(raw):
            return IngestionOutcome("quarantined", reason_code="DATASET_LABEL_FIELD_FORBIDDEN")
        adapter = ADAPTERS.get(source)
        if adapter is None:
            return IngestionOutcome("quarantined", reason_code="UNKNOWN_SOURCE")
        try:
            event = adapter.adapt(raw)
        except (AdapterError, ValueError) as exc:
            return IngestionOutcome(
                "quarantined", reason_code=getattr(exc, "reason_code", "VALIDATION_ERROR")
            )
        self.accepted_events.append(event)
        return IngestionOutcome("accepted", event=event)

    def ingest_group(self, records: Sequence[tuple[str, dict]]) -> list[IngestionOutcome]:
        return [self.ingest(source, raw) for source, raw in records]


class PersistentIngestionSink:
    """Runtime sink: simulator records traverse the same pipeline as API records."""

    def ingest(self, source: str, raw: dict) -> IngestionOutcome:
        return self.ingest_group(((source, raw),))[0]

    def ingest_group(self, records: Sequence[tuple[str, dict]]) -> list[IngestionOutcome]:
        """Persist one simulator timestamp group and publish it as one batch.

        All accepted rows are visible before detection/incident attachment begins.
        This preserves same-timestamp context such as stable raw ingress while
        still publishing at most one RCA revision per affected incident.
        """
        from app.orchestration.publisher import OrchestrationPublisher

        outcomes: list[IngestionOutcome] = []
        accepted_events: list[CanonicalEvent] = []
        with session_scope() as session:
            pipeline = IngestionPipeline()
            for source, raw in records:
                request_id = self._request_id(source, raw)
                result = pipeline.ingest(
                    source=source,
                    raw=raw,
                    request_id=request_id,
                    session=session,
                    publish=False,
                )
                if result.status == "quarantined":
                    reason = result.reason_codes[0] if result.reason_codes else "UNKNOWN"
                    outcomes.append(IngestionOutcome("quarantined", reason_code=reason))
                    continue
                if result.status == "collapsed":
                    outcomes.append(IngestionOutcome("collapsed"))
                    continue

                row = session.get(Event, result.event_id) if result.event_id else None
                event = event_to_contract(row) if row else None
                outcomes.append(IngestionOutcome("accepted", event=event))
                if event is not None and not result.reason_codes:
                    accepted_events.append(event)

            if accepted_events:
                OrchestrationPublisher(session).publish_batch(accepted_events)
        return outcomes

    @staticmethod
    def _request_id(source: str, raw: dict) -> str:
        request_material = json.dumps(
            {"source": source, "raw": raw},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return "simulator:" + hashlib.sha256(request_material.encode("utf-8")).hexdigest()[:24]
