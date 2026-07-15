from __future__ import annotations

from app.config import settings
from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.common import record
from app.detection.detector import DetectionContext


class TraceLatencyDetector:
    detector_id = "trace_latency_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        if event.modality.value != "trace" or event.signal_value is None:
            return []
        expected = event.raw_payload.get("expected_p99_ms")
        if not isinstance(expected, (int, float)) or expected <= 0:
            return []
        observed = float(event.signal_value)
        threshold = float(expected) * 3.0
        if observed < threshold:
            return []
        score = min(1.0, round(0.82 + 0.18 * min(observed / threshold - 1, 1), 2))
        if score < settings.anomaly_threshold:
            return []
        return [
            record(
                event,
                context,
                detector_id=self.detector_id,
                anomaly_type="TRACE_LATENCY_ANOMALY",
                score=score,
                features={
                    "span_id": event.raw_payload.get("span_id"),
                    "operation": event.raw_payload.get("operation"),
                    "observed_ms": observed,
                    "expected_p99_ms": float(expected),
                    "threshold_ms": threshold,
                },
                explanation=(
                    f"Trace span {event.raw_payload.get('operation', 'unknown')} took "
                    f"{observed:g} ms against expected p99 {float(expected):g} ms."
                ),
            )
        ]


class TraceStructureDetector:
    detector_id = "trace_structure_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        if event.modality.value != "trace":
            return []
        parent_span_id = event.raw_payload.get("parent_span_id")
        if not parent_span_id:
            return []
        observed_span_ids = {
            item.raw_payload.get("span_id")
            for item in context.history
            if item.modality.value == "trace"
            and item.trace_or_session_id == event.trace_or_session_id
        }
        if parent_span_id in observed_span_ids:
            return []
        return [
            record(
                event,
                context,
                detector_id=self.detector_id,
                anomaly_type="TRACE_STRUCTURE_ANOMALY",
                score=0.9,
                features={
                    "span_id": event.raw_payload.get("span_id"),
                    "missing_parent_span_id": parent_span_id,
                    "trace_id": event.trace_or_session_id,
                },
                explanation=(
                    f"Trace span {event.raw_payload.get('span_id')} references missing "
                    f"parent span {parent_span_id}."
                ),
            )
        ]
