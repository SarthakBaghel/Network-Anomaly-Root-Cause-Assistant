from __future__ import annotations

from app.config import settings
from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.common import record
from app.detection.detector import DetectionContext


ALERT_TYPES = {
    "HIGH_FORWARDED_REQUEST_AND_CONNECTION_RATE": "GATEWAY_TRAFFIC_ALERT",
    "HIGH_CHECKOUT_ERROR_RATE": "CHECKOUT_ERROR_ALERT",
}


class AlertSeverityDetector:
    detector_id = "alert_severity_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        if event.modality.value != "alert" or event.severity < settings.anomaly_threshold:
            return []
        anomaly_type = ALERT_TYPES.get(event.event_type, event.event_type)
        return [record(
            event, context, detector_id=self.detector_id, anomaly_type=anomaly_type,
            score=event.severity, features={"source_record_id": event.source_record_id},
            explanation=f"Alert {event.event_type} has normalized severity {event.severity:.2f}.",
        )]
