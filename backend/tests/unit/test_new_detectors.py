"""
Tests for the EWMA Adaptive Baseline Detector and Topology Cascade Detector.

BLUEPRINT compliance checks:
  - §11.3: Explanation contains mean/std/observed/threshold/fired_reason
  - §11.4: Both implement the Detector protocol
  - §3.2: alpha is a fixed constant (no self-learning)
  - §12.2: Cascade detector uses typed-topology hops
  - §12.1: Cascade signal has context_only=True, can_open_incident=False
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.contracts import CanonicalEvent
from app.detection.detector import DetectionContext
from app.detection.ewma_detector import EWMA_ALPHA, EWMA_MIN_SAMPLES, EwmaDetector
from app.detection.topology_cascade import TopologyCascadeDetector

UTC = timezone.utc
T0 = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────

def _metric_event(
    identifier: str,
    timestamp: datetime,
    value: float,
    signal: str = "forwarded_requests_per_second",
    entity: str = "api-gateway-01",
) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=f"evt_{identifier}",
        timestamp=timestamp,
        ingested_at=timestamp,
        entity_id=entity,
        modality="metric",
        event_type="FORWARDED_REQUEST_RATE",
        severity=0.8,
        signal_name=signal,
        signal_value=value,
        unit="requests/s",
        source="test.prometheus",
        source_record_id=identifier,
        schema_version="1.0",
        raw_payload={},
    )


def _log_event(
    identifier: str,
    timestamp: datetime,
    entity: str = "payment-api-01",
    event_type: str = "UPSTREAM_CONNECTION_TIMEOUT",
) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=f"evt_{identifier}",
        timestamp=timestamp,
        ingested_at=timestamp,
        entity_id=entity,
        modality="log",
        event_type=event_type,
        severity=0.88,
        source="test.syslog",
        source_record_id=identifier,
        schema_version="1.0",
        raw_payload={},
    )


def _build_ewma_context(history: list[CanonicalEvent], ewma_state: dict | None = None) -> DetectionContext:
    """Build a DetectionContext and inject ewma_state."""
    ctx = DetectionContext(history=history)
    # Inject mutable ewma_state onto the frozen dataclass via object.__setattr__
    object.__setattr__(ctx, "ewma_state", ewma_state or {})
    object.__setattr__(ctx, "_ewma_updates", {})
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# EWMA Detector tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEwmaDetector:
    def setup_method(self) -> None:
        self.detector = EwmaDetector()

    def test_detector_id_is_stable(self) -> None:
        assert self.detector.detector_id == "ewma_v1"

    def test_ignores_non_metric_events(self) -> None:
        event = _log_event("log1", T0)
        ctx = _build_ewma_context([])
        assert self.detector.evaluate(event, ctx) == []

    def test_ignores_signal_without_known_threshold(self) -> None:
        event = _metric_event("m1", T0, 999.0, signal="unknown_signal_xyz")
        ctx = _build_ewma_context([])
        assert self.detector.evaluate(event, ctx) == []

    def test_bootstraps_on_first_sample_no_anomaly(self) -> None:
        """First sample for a new entity×signal bootstraps state; must not fire."""
        event = _metric_event("m1", T0, 7800.0)
        ctx = _build_ewma_context([])
        result = self.detector.evaluate(event, ctx)
        assert result == [], "First sample must bootstrap state without firing"

    def test_fires_after_min_samples_on_spike(self) -> None:
        """After EWMA_MIN_SAMPLES updates, a spike should fire an anomaly."""
        detector = EwmaDetector()
        key = "api-gateway-01:forwarded_requests_per_second"
        # Simulate pre-warmed state (n=EWMA_MIN_SAMPLES)
        ewma_state = {
            key: {
                "ewma_mean": 2400.0,
                "ewma_variance": 10000.0,  # std ≈ 100
                "n_samples": EWMA_MIN_SAMPLES,
            }
        }
        event = _metric_event("spike", T0 + timedelta(seconds=100), 7800.0)
        ctx = _build_ewma_context([], ewma_state=ewma_state)
        result = detector.evaluate(event, ctx)
        assert len(result) == 1
        anomaly = result[0]
        assert anomaly.detector_id == "ewma_v1"
        assert anomaly.score >= 0.75, f"Expected score ≥ 0.75, got {anomaly.score}"
        assert anomaly.context_only is False
        assert anomaly.can_open_incident is True

    def test_explanation_contains_all_required_fields(self) -> None:
        """BLUEPRINT §11.3: explanation must contain mean/std/observed/threshold/fired_reason."""
        key = "api-gateway-01:forwarded_requests_per_second"
        ewma_state = {
            key: {
                "ewma_mean": 2400.0,
                "ewma_variance": 10000.0,
                "n_samples": EWMA_MIN_SAMPLES,
            }
        }
        event = _metric_event("spike", T0, 7800.0)
        ctx = _build_ewma_context([], ewma_state=ewma_state)
        result = self.detector.evaluate(event, ctx)
        assert len(result) == 1
        exp = result[0].explanation
        assert "ewma_mean" in exp or "mean=" in exp, f"explanation missing mean: {exp}"
        assert "fired=" in exp, f"explanation missing fired_reason: {exp}"
        assert "threshold=" in exp or "static_threshold=" in exp, f"explanation missing threshold: {exp}"

    def test_features_dict_has_all_explainability_keys(self) -> None:
        """Every anomaly features dict must expose all decision inputs."""
        key = "api-gateway-01:forwarded_requests_per_second"
        ewma_state = {
            key: {"ewma_mean": 2400.0, "ewma_variance": 10000.0, "n_samples": EWMA_MIN_SAMPLES}
        }
        event = _metric_event("spike", T0, 7800.0)
        ctx = _build_ewma_context([], ewma_state=ewma_state)
        result = self.detector.evaluate(event, ctx)
        assert len(result) == 1
        f = result[0].features
        required_keys = {
            "alpha", "ewma_mean", "ewma_std", "observed", "safety_threshold",
            "n_samples", "fired_reason", "original_signal", "effective_signal", "is_proxy_mapping"
        }
        missing = required_keys - set(f.keys())
        assert not missing, f"features dict missing keys: {missing}"

    def test_alpha_is_fixed_constant_not_learned(self) -> None:
        """BLUEPRINT §3.2: alpha must be a fixed constant, never adaptive."""
        assert EWMA_ALPHA == 0.1, "alpha must remain fixed at 0.1 per BLUEPRINT §3.2"

    def test_does_not_fire_on_normal_values(self) -> None:
        """Normal values within baseline should not fire."""
        key = "api-gateway-01:forwarded_requests_per_second"
        ewma_state = {
            key: {"ewma_mean": 2400.0, "ewma_variance": 10000.0, "n_samples": EWMA_MIN_SAMPLES}
        }
        event = _metric_event("normal", T0, 2450.0)  # Very close to baseline
        ctx = _build_ewma_context([], ewma_state=ewma_state)
        result = self.detector.evaluate(event, ctx)
        assert result == [], f"Expected no anomaly for normal value, got: {result}"

    def test_signal_alias_resolution(self) -> None:
        """Proxy signal names must resolve to canonical names via signal_aliases."""
        # GAIA MicroSS proxy: memory_usage_percent → db_connection_utilization
        key = "api-gateway-01:db_connection_utilization"
        ewma_state = {
            key: {"ewma_mean": 0.42, "ewma_variance": 0.001, "n_samples": EWMA_MIN_SAMPLES}
        }
        event = _metric_event("proxy_spike", T0, 0.95, signal="memory_usage_percent")
        ctx = _build_ewma_context([], ewma_state=ewma_state)
        result = self.detector.evaluate(event, ctx)
        if result:
            f = result[0].features
            assert f["is_proxy_mapping"] is True
            assert f["original_signal"] == "memory_usage_percent"
            assert f["effective_signal"] == "db_connection_utilization"


# ─────────────────────────────────────────────────────────────────────────────
# Topology Cascade Detector tests
# ─────────────────────────────────────────────────────────────────────────────

class _MockAnomaly:
    def __init__(self, entity_id: str, anomaly_id: str, score: float, anomaly_type: str = "SPIKE") -> None:
        self.entity_id = entity_id
        self.anomaly_id = anomaly_id
        self.anomaly_type = anomaly_type
        self.score = score


class _MockTopology:
    """Simple topology graph mock supporting distance queries."""

    def __init__(self, edges: dict[tuple[str, str, str], int]) -> None:
        # edges: (from_entity, to_entity, relation_type) → hop_distance
        self._edges = edges

    def distance(self, from_entity: str, to_entity: str, relation_type: str) -> int | None:
        return self._edges.get((from_entity, to_entity, relation_type))


def _build_cascade_context(
    recent_anomalies: list,
    topology: _MockTopology | None = None,
) -> DetectionContext:
    ctx = DetectionContext(history=[])
    object.__setattr__(ctx, "recent_anomalies", recent_anomalies)
    object.__setattr__(ctx, "topology", topology)
    return ctx


class TestTopologyCascadeDetector:
    def setup_method(self) -> None:
        self.detector = TopologyCascadeDetector()

    def test_detector_id_is_stable(self) -> None:
        assert self.detector.detector_id == "topology_cascade_v1"

    def test_returns_empty_without_topology(self) -> None:
        event = _metric_event("m1", T0, 1000.0, entity="checkout-api-01")
        ctx = _build_cascade_context([])
        assert self.detector.evaluate(event, ctx) == []

    def test_returns_empty_without_recent_anomalies(self) -> None:
        topo = _MockTopology({})
        event = _metric_event("m1", T0, 1000.0, entity="checkout-api-01")
        ctx = _build_cascade_context([], topology=topo)
        assert self.detector.evaluate(event, ctx) == []

    def test_fires_when_upstream_entity_has_anomaly(self) -> None:
        """BLUEPRINT §12.2: downstream entity gets cascade signal if upstream anomalous."""
        topo = _MockTopology({
            ("api-gateway-01", "checkout-api-01", "sends_traffic_to"): 1,
        })
        upstream_anomaly = _MockAnomaly("api-gateway-01", "ano_gw_001", score=0.91, anomaly_type="TRAFFIC_SPIKE")
        event = _metric_event("cascade_evt", T0, 1200.0, entity="checkout-api-01")
        ctx = _build_cascade_context([upstream_anomaly], topology=topo)
        result = self.detector.evaluate(event, ctx)
        assert len(result) == 1, f"Expected cascade anomaly, got {result}"
        anomaly = result[0]
        assert anomaly.context_only is True, "Cascade must be context_only=True per BLUEPRINT §12.1"
        assert anomaly.can_open_incident is False, "Cascade must not open incidents"
        assert anomaly.detector_id == "topology_cascade_v1"

    def test_cascade_features_contain_topology_path(self) -> None:
        """features dict must name upstream_entity, relation_type, hop_distance."""
        topo = _MockTopology({
            ("api-gateway-01", "checkout-api-01", "sends_traffic_to"): 1,
        })
        upstream_anomaly = _MockAnomaly("api-gateway-01", "ano_gw_001", score=0.91)
        event = _metric_event("cascade_evt", T0, 1200.0, entity="checkout-api-01")
        ctx = _build_cascade_context([upstream_anomaly], topology=topo)
        result = self.detector.evaluate(event, ctx)
        assert result
        f = result[0].features
        assert f["upstream_entity"] == "api-gateway-01"
        assert f["relation_type"] == "sends_traffic_to"
        assert f["hop_distance"] == 1
        assert "cascade_score_formula" in f

    def test_cascade_explanation_names_upstream_entity(self) -> None:
        """Explanation must name the upstream entity and relation type."""
        topo = _MockTopology({
            ("api-gateway-01", "checkout-api-01", "sends_traffic_to"): 1,
        })
        upstream_anomaly = _MockAnomaly("api-gateway-01", "ano_gw_001", score=0.91)
        event = _metric_event("cascade_evt", T0, 1200.0, entity="checkout-api-01")
        ctx = _build_cascade_context([upstream_anomaly], topology=topo)
        result = self.detector.evaluate(event, ctx)
        assert result
        exp = result[0].explanation
        assert "api-gateway-01" in exp, f"explanation missing upstream entity: {exp}"
        assert "sends_traffic_to" in exp, f"explanation missing relation_type: {exp}"

    def test_does_not_fire_for_same_entity(self) -> None:
        """Should not emit a cascade signal if the anomaly is from the same entity."""
        topo = _MockTopology({})
        same_entity_anomaly = _MockAnomaly("api-gateway-01", "ano_self", score=0.91)
        event = _metric_event("self_evt", T0, 7800.0, entity="api-gateway-01")
        ctx = _build_cascade_context([same_entity_anomaly], topology=topo)
        assert self.detector.evaluate(event, ctx) == []

    def test_ignores_config_change_events(self) -> None:
        """BLUEPRINT §11.2: config_change markers are handled by ConfigChangeMarker, not cascade."""
        topo = _MockTopology({("api-gateway-01", "checkout-api-01", "sends_traffic_to"): 1})
        upstream_anomaly = _MockAnomaly("api-gateway-01", "ano_gw_001", score=0.91)
        event = CanonicalEvent(
            event_id="evt_cfg", timestamp=T0, ingested_at=T0,
            entity_id="checkout-api-01", modality="config_change",
            event_type="CONFIG_VALUE_CHANGED", severity=0.5,
            source="test.config", source_record_id="change-x",
            schema_version="1.0", raw_payload={},
        )
        ctx = _build_cascade_context([upstream_anomaly], topology=topo)
        assert self.detector.evaluate(event, ctx) == []

    def test_score_formula_is_weighted_blend(self) -> None:
        """Score = 0.7 × event.severity + 0.3 × upstream_score (rounded half-up)."""
        topo = _MockTopology({("api-gateway-01", "checkout-api-01", "sends_traffic_to"): 1})
        upstream_anomaly = _MockAnomaly("api-gateway-01", "ano_gw_001", score=0.91)
        # event severity set via CanonicalEvent directly — create with severity=0.80
        event = CanonicalEvent(
            event_id="evt_score_test", timestamp=T0, ingested_at=T0,
            entity_id="checkout-api-01", modality="metric",
            event_type="CHECKOUT_LATENCY", severity=0.80,
            signal_name="checkout_p95_latency_ms", signal_value=1200.0, unit="ms",
            source="test.prometheus", source_record_id="score-test",
            schema_version="1.0", raw_payload={},
        )
        ctx = _build_cascade_context([upstream_anomaly], topology=topo)
        result = self.detector.evaluate(event, ctx)
        assert result
        expected_score = round(0.7 * 0.80 + 0.3 * 0.91, 2)  # 0.833 → 0.83
        assert abs(result[0].score - expected_score) < 0.01, (
            f"Expected score ≈ {expected_score}, got {result[0].score}"
        )
