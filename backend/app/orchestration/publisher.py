from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.contracts import CanonicalEvent

class OrchestrationPublisher:
    def __init__(self, session: Session) -> None:
        self.session = session

    def publish(self, event: CanonicalEvent) -> None:
        from app.db.models import Event
        from app.orchestration.orchestrator import orchestrator
        db_event = self.session.get(Event, event.event_id)
        if db_event is not None:
            orchestrator.process_event(db_event, self.session)

    def publish_batch(self, events: list[CanonicalEvent]) -> None:
        from app.db.models import Event
        from app.orchestration.orchestrator import orchestrator
        rows = [
            row
            for event in events
            if (row := self.session.get(Event, event.event_id)) is not None
        ]
        if rows:
            orchestrator.process_batch(rows, self.session)
