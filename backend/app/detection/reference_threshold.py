from __future__ import annotations

from app.config import settings
from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.common import record
from app.detection.detector import DetectionContext


ANOMALY_TYPES = {
    "packet_loss_rate": "PACKET_LOSS_SPIKE",
    "network_latency_ms": "NETWORK_LATENCY_HIGH",
    "raw_ingress_requests_per_second": "RAW_INGRESS_TRAFFIC_SPIKE",
    "forwarded_requests_per_second": "FORWARDED_TRAFFIC_SPIKE",
    "active_connections_total": "ACTIVE_CONNECTION_SPIKE",
    "syn_error_rate": "SYN_ERROR_RATE_HIGH",
    "source_distribution_change_score": "SOURCE_DISTRIBUTION_CHANGE",
    "cpu_usage_percent": "CPU_SATURATION",
    "memory_usage_percent": "MEMORY_SATURATION",
    "service_p95_latency_ms": "SERVICE_LATENCY_HIGH",
    "unique_destination_ports": "PORT_FANOUT_HIGH",
    "rejected_connection_rate": "REJECTED_CONNECTION_SPIKE",
    "destination_fanout": "DESTINATION_FANOUT_HIGH",
    "datanode_io_error_rate": "DATANODE_IO_ERRORS",
}


class ReferenceThresholdDetector:
    """Apply declared safety limits to curated, reference-derived demo signals.

    These scenarios intentionally do not manufacture a per-signal rolling baseline.
    Restricting this detector to ``REFERENCE_DERIVED`` events keeps the production
    baseline contract unchanged while making each reference scenario auditable.
    """

    detector_id = "reference_threshold_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        provenance = event.raw_payload.get("provenance")
        if (
            event.modality.value != "metric"
            or "REFERENCE_DERIVED" not in event.quality_flags
            or not isinstance(provenance, dict)
            or provenance.get("transformation_version") != "reference-scenario-builder-1.0"
            or event.signal_name is None
            or event.signal_value is None
        ):
            return []
        threshold = context.safety_thresholds.get(event.signal_name)
        anomaly_type = ANOMALY_TYPES.get(event.signal_name)
        if threshold is None or threshold <= 0 or anomaly_type is None:
            return []
        observed = float(event.signal_value)
        if observed < threshold:
            return []
        exceedance = min(observed / threshold - 1.0, 1.0)
        score = round(0.85 + 0.15 * exceedance, 2)
        if score < settings.anomaly_threshold:
            return []
        return [
            record(
                event,
                context,
                detector_id=self.detector_id,
                anomaly_type=anomaly_type,
                score=score,
                features={
                    "source_record_id": event.source_record_id,
                    "observed": observed,
                    "safety_threshold": threshold,
                    "fired_reason": "reference_safety_threshold",
                    "quality_flag": "REFERENCE_DERIVED",
                },
                explanation=(
                    f"Reference-derived signal {event.signal_name} observed {observed:g} "
                    f"at or above its declared safety threshold {threshold:g}."
                ),
            )
        ]
