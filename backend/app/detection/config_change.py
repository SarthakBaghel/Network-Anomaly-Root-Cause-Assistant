from __future__ import annotations

from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.common import record
from app.detection.detector import DetectionContext


class ConfigChangeMarker:
    detector_id = "config_change_marker_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        if event.modality.value != "config_change":
            return []
        return [record(
            event, context, detector_id=self.detector_id,
            anomaly_type="RECENT_CONFIGURATION_CHANGE", score=event.severity,
            context_only=True, can_open_incident=False,
            features={"change_ticket": event.raw_payload.get("change_ticket")},
            explanation="Configuration changes are retained as context and cannot open an incident.",
        )]
