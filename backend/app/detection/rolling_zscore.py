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
        # Resolve proxy/alias signal name to canonical monitored name (BLUEPRINT §3.3.4)
        effective_signal = context.signal_aliases.get(event.signal_name, event.signal_name)
        is_proxy = effective_signal != event.signal_name
        safety_threshold = context.safety_thresholds.get(effective_signal)
        if safety_threshold is None or safety_threshold <= 0:
            return []
        samples = [
            item for item in context.history
            if item.modality.value == "metric"
            and item.entity_id == event.entity_id
            and (
                # Match on original signal name OR its resolved canonical name
                item.signal_name == event.signal_name
                or (is_proxy and item.signal_name == effective_signal)
            )
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
            effective_signal not in STATIC_ONLY_SIGNALS
            and z_score is not None
            and abs(z_score) >= settings.metric_zscore_threshold
        )
        if not (z_fired or static_fired):
            return []
        score = metric_score(z_score, observed, safety_threshold, static_fired=static_fired)
        if score < settings.anomaly_threshold:
            return []
        anomaly_type = ANOMALY_TYPES.get(effective_signal, f"{event.event_type}_ANOMALY")
        features = {
            "source_record_id": event.source_record_id,
            "z_score": None if z_score is None else round(z_score, 4),
            "baseline_mean": round(baseline_mean, 4),
            "baseline_std": round(baseline_std, 4),
            "observed": observed,
            "safety_threshold": safety_threshold,
            "baseline_points": len(samples),
            "fired_reason": "z_score" if z_fired else "static_threshold",
            "original_signal": event.signal_name,
            "effective_signal": effective_signal,
            "is_proxy_mapping": is_proxy,
        }
        proxy_note = f" [proxy: {event.signal_name} → {effective_signal}]" if is_proxy else ""
        return [record(
            event, context, detector_id=self.detector_id, anomaly_type=anomaly_type,
            score=score, features=features,
            explanation=(
                f"{effective_signal}{proxy_note} observed {observed:g} against "
                f"rolling mean {baseline_mean:g} ± {baseline_std:g} "
                f"(z={z_score if z_score is not None else 'zero-variance'}, "
                f"threshold={safety_threshold:g}, fired={features['fired_reason']})."
            ),
        )]
