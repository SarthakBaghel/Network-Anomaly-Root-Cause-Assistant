from __future__ import annotations

from app.config import settings
from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.common import record
from app.detection.detector import DetectionContext
from app.ingestion.catalogue import log_rule


FALLBACK_RULES = {
    "UPSTREAM_TIMEOUT": ("UPSTREAM_TIMEOUT", 0.86),
    "CONN_REFUSED": ("CONNECTION_REFUSED", 0.85),
}


class LogRuleDetector:
    detector_id = "log_rule_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        if event.modality.value != "log":
            return []
        catalogue_rule = log_rule(event.event_type)
        if catalogue_rule:
            anomaly_type = str(catalogue_rule["anomaly_type"])
            score = float(catalogue_rule["anomaly_score"])
            rule_id = str(catalogue_rule["template_id"])
        elif event.event_type in FALLBACK_RULES:
            anomaly_type, score = FALLBACK_RULES[event.event_type]
            rule_id = event.event_type.lower()
        else:
            level = str(event.raw_payload.get("level", "")).lower()
            if level not in {"error", "critical", "fatal"}:
                return []
            score = {"error": 0.8, "critical": 0.95, "fatal": 1.0}[level]
            anomaly_type = "FATAL_LOG_PATTERN" if level == "fatal" else "ERROR_LOG_PATTERN"
            rule_id = f"log_level_{level}"
        if score < settings.anomaly_threshold:
            return []
        return [record(
            event, context, detector_id=self.detector_id, anomaly_type=anomaly_type,
            score=score, features={"source_record_id": event.source_record_id, "rule_id": rule_id},
            explanation=f"Log event {event.event_type} matched rule {rule_id}.",
        )]
