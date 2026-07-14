from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import AnomalyRecord, CanonicalEvent
from app.db.models import Anomaly, Event
from app.detection.alert_severity import AlertSeverityDetector
from app.detection.config_change import ConfigChangeMarker
from app.detection.detector import DetectionContext, Detector
from app.detection.log_rule import LogRuleDetector
from app.detection.rolling_zscore import RollingZscoreDetector
from app.config import settings


DETECTORS: tuple[Detector, ...] = (
    RollingZscoreDetector(),
    LogRuleDetector(),
    AlertSeverityDetector(),
    ConfigChangeMarker(),
)


class DetectionPublisher:
    """Synchronous Phase-3 boundary invoked after accepted-event persistence."""

    def __init__(self, session: Session, detectors: tuple[Detector, ...] = DETECTORS) -> None:
        self.session = session
        self.detectors = detectors

    def publish(self, event: CanonicalEvent) -> None:
        self._evaluate_and_persist(event)

    def publish_batch(self, events: list[CanonicalEvent]) -> None:
        for event in sorted(events, key=lambda item: (item.timestamp, item.event_id)):
            self._evaluate_and_persist(event)

    def _evaluate_and_persist(self, event: CanonicalEvent) -> list[AnomalyRecord]:
        from app.ingestion.pipeline import event_to_contract

        history_rows = self.session.scalars(select(Event).where(
            Event.timestamp >= event.timestamp - timedelta(seconds=settings.detector_window_seconds),
            Event.timestamp < event.timestamp,
        ).order_by(Event.timestamp, Event.id))
        context = DetectionContext(history=[event_to_contract(row) for row in history_rows])
        records: list[AnomalyRecord] = []
        for detector in self.detectors:
            for anomaly in detector.evaluate(event, context):
                exists = self.session.scalar(select(Anomaly.id).where(
                    Anomaly.event_id == anomaly.event_id,
                    Anomaly.detector_id == anomaly.detector_id,
                ))
                if exists is not None:
                    continue
                self.session.add(Anomaly(
                    id=anomaly.anomaly_id,
                    event_id=anomaly.event_id,
                    detector_id=anomaly.detector_id,
                    type=anomaly.anomaly_type,
                    detected_at=anomaly.detected_at,
                    score=anomaly.score,
                    threshold=anomaly.threshold,
                    context_only=anomaly.context_only,
                    can_open_incident=anomaly.can_open_incident,
                    window_start=anomaly.window_start,
                    window_end=anomaly.window_end,
                    features=anomaly.features,
                    explanation=anomaly.explanation,
                ))
                records.append(anomaly)
        self.session.flush()
        return records
