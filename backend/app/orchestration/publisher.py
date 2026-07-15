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
        # Process in timestamp order, then ID order
        sorted_events = sorted(events, key=lambda e: (e.timestamp, e.event_id))
        for event in sorted_events:
            db_event = self.session.get(Event, event.event_id)
            if db_event is not None:
                orchestrator.process_event(db_event, self.session)
