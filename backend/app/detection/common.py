from __future__ import annotations

import hashlib
from datetime import timedelta

from app.config import settings
from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.detector import DetectionContext


def anomaly_id(event: CanonicalEvent, *, context_only: bool = False, detector_id: str = "") -> str:
    prefix = "ctx" if context_only else "ano"
    digest = event.event_id.removeprefix("evt_")
    if not digest:
        digest = hashlib.sha256(event.event_id.encode()).hexdigest()[:24]
    # Include detector_id suffix so multiple detectors firing on the same event
    # produce distinct anomaly IDs (prevents UNIQUE PK conflicts on anomalies.id).
    det_suffix = f"_{detector_id[:8]}" if detector_id else ""
    return f"{prefix}_{digest}{det_suffix}"


def record(
    event: CanonicalEvent,
    context: DetectionContext,
    *,
    detector_id: str,
    anomaly_type: str,
    score: float,
    explanation: str,
    features: dict,
    context_only: bool = False,
    can_open_incident: bool = True,
) -> AnomalyRecord:
    return AnomalyRecord(
        anomaly_id=anomaly_id(event, context_only=context_only, detector_id=detector_id),
        event_id=event.event_id,
        detector_id=detector_id,
        detected_at=context.detected_at or event.timestamp + timedelta(milliseconds=200),
        anomaly_type=anomaly_type,
        score=score,
        threshold=settings.anomaly_threshold,
        context_only=context_only,
        can_open_incident=can_open_incident,
        window_start=event.timestamp - timedelta(seconds=settings.detector_window_seconds),
        window_end=event.timestamp,
        features=features,
        explanation=explanation,
    )
