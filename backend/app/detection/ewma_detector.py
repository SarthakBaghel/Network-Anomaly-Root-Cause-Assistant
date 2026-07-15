"""
EWMA (Exponentially Weighted Moving Average) Anomaly Detector.

Implements the same Detector protocol as RollingZscoreDetector, providing
an adaptive baseline that adjusts to gradual load changes without requiring
a fixed-size warmup window.

Key differences from rolling_zscore_v1:
  - Uses EWMA mean/variance (per entity × signal pair) instead of a rolling window
  - alpha=0.1 is a FIXED decay constant (declared in config) — this is NOT self-learning
  - Works from the first sample (no min_baseline_points warmup required)
  - Fires when |z_ewma| >= threshold OR observed >= safety_threshold
  - All decision inputs stored in features dict for full explainability

BLUEPRINT compliance:
  - §11.4: Implements the same Detector protocol
  - §3.2: alpha is fixed — no self-learning weights
  - §11.3: Explanation template contains mean/std/observed/threshold/fired_reason
  - §3.3.4: Proxy mapping handled via signal_aliases from DetectionContext

EWMA state is persisted in the ewma_baselines table so it survives restarts.
State is cleared on POST /simulator/reset to restore deterministic demo state.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.config import settings
from app.contracts import AnomalyRecord, CanonicalEvent
from app.detection.common import record
from app.detection.detector import DetectionContext

if TYPE_CHECKING:
    pass

# Fixed alpha — declared here and in settings for audit trail
# BLUEPRINT §3.2: this is NOT learned; it is a configuration constant
EWMA_ALPHA: float = 0.1

# Minimum samples before EWMA variance is considered reliable enough to fire z-score
EWMA_MIN_SAMPLES: int = 5

# EWMA anomaly types (same vocabulary as rolling_zscore_v1)
ANOMALY_TYPES = {
    "forwarded_requests_per_second": "FORWARDED_TRAFFIC_SPIKE",
    "active_connections_total":      "ACTIVE_CONNECTION_SPIKE",
    "connection_utilization":        "CONNECTION_UTILIZATION_HIGH",
    "tcp_resets_total":              "TCP_RESET_SPIKE",
    "tcp_retransmissions_total":     "TCP_RETRANSMISSION_SPIKE",
    "checkout_p95_latency_ms":       "CHECKOUT_LATENCY_HIGH",
    "db_connection_utilization":     "DB_CONNECTION_UTILIZATION_HIGH",
    "memory_usage_percent":          "MEMORY_SATURATION",
    "cpu_usage_percent":             "CPU_SATURATION",
    "network_latency_ms":            "NETWORK_LATENCY_HIGH",
}

STATIC_ONLY_SIGNALS = {"db_connection_utilization"}


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _ewma_score(z_score: float | None, observed: float, safety_threshold: float, *, static_fired: bool = False) -> float:
    """Mirror of rolling_zscore metric_score formula for consistent scoring."""
    if z_score is None:
        z_component = 1.0 if static_fired else 0.0
    else:
        z_component = _clamp(abs(z_score) / 5.0)
    threshold_component = _clamp(observed / safety_threshold)
    value = Decimal(str(0.6 * z_component + 0.4 * threshold_component))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class EwmaDetector:
    """EWMA adaptive baseline anomaly detector.

    Maintains per-(entity_id, signal_name) exponentially weighted mean and
    variance. On each new metric event, updates state and evaluates whether
    the observation is anomalous relative to the adaptive baseline.

    State is read from and written to the ewma_baselines SQLite table via
    the provided session. Callers must commit or flush after calling evaluate().
    """

    detector_id = "ewma_v1"

    def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]:
        if event.modality.value != "metric" or event.signal_name is None or event.signal_value is None:
            return []

        # Resolve proxy/alias to canonical signal name (BLUEPRINT §3.3.4)
        effective_signal = context.signal_aliases.get(event.signal_name, event.signal_name)
        is_proxy = effective_signal != event.signal_name
        safety_threshold = context.safety_thresholds.get(effective_signal)
        if safety_threshold is None or safety_threshold <= 0:
            return []

        # Load EWMA state from context (injected by DetectorService)
        ewma_state = getattr(context, "ewma_state", {})
        key = f"{event.entity_id}:{effective_signal}"
        state = ewma_state.get(key)

        observed = float(event.signal_value)

        if state is None:
            # Bootstrap: initialise state, no anomaly on first sample
            new_state = {
                "ewma_mean": observed,
                "ewma_variance": 0.0,
                "n_samples": 1,
            }
            ewma_state[key] = new_state
            # Signal to context holder to persist
            if hasattr(context, "_ewma_updates"):
                context._ewma_updates[key] = (event.entity_id, effective_signal, new_state)
            return []

        # Update EWMA state
        n = state["n_samples"]
        mean = state["ewma_mean"]
        variance = state["ewma_variance"]

        delta = observed - mean
        new_mean = mean + EWMA_ALPHA * delta
        new_variance = (1 - EWMA_ALPHA) * (variance + EWMA_ALPHA * delta ** 2)
        new_n = n + 1
        ewma_std = math.sqrt(new_variance) if new_variance > 0 else 0.0

        # Persist updated state
        updated_state = {"ewma_mean": new_mean, "ewma_variance": new_variance, "n_samples": new_n}
        ewma_state[key] = updated_state
        if hasattr(context, "_ewma_updates"):
            context._ewma_updates[key] = (event.entity_id, effective_signal, updated_state)

        # Need minimum samples for reliable z-score
        if new_n < EWMA_MIN_SAMPLES:
            return []

        # Compute z-score against EWMA baseline
        z_score = (delta / ewma_std) if ewma_std > 0 else None
        static_fired = observed >= safety_threshold
        z_fired = (
            effective_signal not in STATIC_ONLY_SIGNALS
            and z_score is not None
            and abs(z_score) >= settings.metric_zscore_threshold
        )
        if not (z_fired or static_fired):
            return []

        # Dynamic upper band (mean + 3.5σ) for display
        dynamic_threshold = new_mean + 3.5 * ewma_std if ewma_std > 0 else safety_threshold
        score = _ewma_score(z_score, observed, safety_threshold, static_fired=static_fired)
        if score < settings.anomaly_threshold:
            return []

        anomaly_type = ANOMALY_TYPES.get(effective_signal, f"{event.event_type}_ANOMALY")
        proxy_note = f" [proxy: {event.signal_name} → {effective_signal}]" if is_proxy else ""
        fired_reason = "z_score" if z_fired else "static_threshold"

        features = {
            "source_record_id": event.source_record_id,
            "detector_algorithm": "ewma",
            "alpha": EWMA_ALPHA,
            "ewma_mean": round(new_mean, 4),
            "ewma_variance": round(new_variance, 4),
            "ewma_std": round(ewma_std, 4),
            "dynamic_threshold": round(dynamic_threshold, 4),
            "observed": observed,
            "safety_threshold": safety_threshold,
            "z_score": None if z_score is None else round(z_score, 4),
            "n_samples": new_n,
            "fired_reason": fired_reason,
            "original_signal": event.signal_name,
            "effective_signal": effective_signal,
            "is_proxy_mapping": is_proxy,
        }
        z_str = f"{z_score:.2f}" if z_score is not None else "N/A"
        explanation = (
            f"{effective_signal}{proxy_note} observed {observed:g} against "
            f"EWMA baseline mean={new_mean:.4g} ±{ewma_std:.4g} "
            f"(z={z_str}, "
            f"alpha={EWMA_ALPHA}, n={new_n}, "
            f"static_threshold={safety_threshold:g}, fired={fired_reason})."
        )
        return [record(
            event, context, detector_id=self.detector_id, anomaly_type=anomaly_type,
            score=score, features=features, explanation=explanation,
        )]
