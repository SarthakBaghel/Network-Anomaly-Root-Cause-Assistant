from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

from app.config import settings
from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.common import record
from app.detection.detector import DetectionContext


ANOMALY_TYPES = {
    "forwarded_requests_per_second": "FORWARDED_TRAFFIC_SPIKE",
    "active_connections_total": "ACTIVE_CONNECTION_SPIKE",
    "connection_utilization": "CONNECTION_UTILIZATION_HIGH",
    "tcp_resets_total": "TCP_RESET_SPIKE",
    "tcp_retransmissions_total": "TCP_RETRANSMISSION_SPIKE",
    "checkout_p95_latency_ms": "CHECKOUT_LATENCY_HIGH",
    "db_connection_utilization": "DB_CONNECTION_UTILIZATION_HIGH",
    "raw_ingress_requests_per_second": "RAW_INGRESS_TRAFFIC_SPIKE",
}

# This signal is a utilization safety gauge: small movements around its normal
# baseline are evidence, while only crossing its configured ceiling is anomalous.
STATIC_ONLY_SIGNALS = {"db_connection_utilization"}


def clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def metric_score(z_score: float | None, observed: float, safety_threshold: float, *, static_fired: bool = False) -> float:
    if z_score is None:
        z_component = 1.0 if static_fired else 0.0
    else:
        z_component = clamp(abs(z_score) / 5.0)
    threshold_component = clamp(observed / safety_threshold)
    value = Decimal(str(0.6 * z_component + 0.4 * threshold_component))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class RollingZscoreDetector:
    detector_id = "rolling_zscore_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        if event.modality.value != "metric" or event.signal_name is None or event.signal_value is None:
            return []
        safety_threshold = context.safety_thresholds.get(event.signal_name)
        if safety_threshold is None or safety_threshold <= 0:
            return []
        samples = [
            item for item in context.history
            if item.modality.value == "metric"
            and item.entity_id == event.entity_id
            and item.signal_name == event.signal_name
            and event.timestamp.timestamp() - settings.detector_window_seconds <= item.timestamp.timestamp() < event.timestamp.timestamp()
            and item.signal_value is not None
        ]
        if len(samples) < settings.detector_min_baseline_points:
            return []

        frame = pd.DataFrame({"timestamp": [item.timestamp for item in samples], "value": [item.signal_value for item in samples]}).sort_values("timestamp")
        rolling = frame.set_index("timestamp")["value"].rolling(f"{settings.detector_window_seconds}s")
        baseline_mean = float(rolling.mean().iloc[-1])
        baseline_std = float(rolling.std(ddof=1).iloc[-1])
        observed = float(event.signal_value)
        static_fired = observed >= safety_threshold
        z_score = None if pd.isna(baseline_std) or baseline_std == 0 else (observed - baseline_mean) / baseline_std
        z_fired = (
            event.signal_name not in STATIC_ONLY_SIGNALS
            and z_score is not None
            and abs(z_score) >= settings.metric_zscore_threshold
        )
        if not (z_fired or static_fired):
            return []
        score = metric_score(z_score, observed, safety_threshold, static_fired=static_fired)
        if score < settings.anomaly_threshold:
            return []
        anomaly_type = ANOMALY_TYPES.get(event.signal_name, f"{event.event_type}_ANOMALY")
        features = {
            "source_record_id": event.source_record_id,
            "z_score": None if z_score is None else round(z_score, 4),
            "baseline_mean": round(baseline_mean, 4),
            "baseline_std": round(baseline_std, 4),
            "observed": observed,
            "safety_threshold": safety_threshold,
            "baseline_points": len(samples),
        }
        return [record(
            event, context, detector_id=self.detector_id, anomaly_type=anomaly_type,
            score=score, features=features,
            explanation=f"{event.signal_name} observed {observed:g} against rolling mean {baseline_mean:g} (z={z_score if z_score is not None else 'zero-variance'}).",
        )]
