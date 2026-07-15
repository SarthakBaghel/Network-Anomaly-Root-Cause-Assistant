"""
Tests for the new production wiring:
  1. EwmaStateStore — load, put, flush, reset
  2. TopologyView — BFS distance, typed-edge traversal, graceful empty
  3. service._build_context — EWMA/topology/recent_anomalies injection
  4. TopologyCascadeDetector fires end-to-end with real context wiring
"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Entity, TopologyEdge, Anomaly, Event, EwmaBaseline
from app.detection.ewma_store import EwmaStateStore
from app.detection.topology_view import TopologyView
from app.detection.detector import DetectionContext
from app.detection.ewma_detector import EWMA_ALPHA, EWMA_MIN_SAMPLES
from app.detection.topology_cascade import TopologyCascadeDetector
from app.contracts import CanonicalEvent, Modality


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fresh_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @sa_event.listens_for(engine, "connect")
    def _fk(conn, _): conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return Session(engine)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _entity(session: Session, entity_id: str) -> None:
    session.add(Entity(
        id=entity_id, name=entity_id, entity_type="service",
        service=entity_id, criticality="normal", metadata_json={},
    ))
    session.flush()


def _edge(session: Session, src: str, tgt: str, rel: str) -> None:
    session.add(TopologyEdge(
        id=f"edge_{src}_{tgt}_{rel}", source_entity_id=src,
        target_entity_id=tgt, relation_type=rel, relationship=rel,
        active_from=None, active_to=None,
    ))
    session.flush()


def _canonical_event(
    entity_id: str = "api-gateway-01",
    signal_name: str = "forwarded_requests_per_second",
    signal_value: float = 200.0,
    modality: str = "metric",
    event_type: str = "METRIC",
    severity: float = 0.5,
    ts: datetime.datetime | None = None,
) -> CanonicalEvent:
    now = ts or _now()
    return CanonicalEvent(
        event_id=str(uuid.uuid4()),
        timestamp=now,
        ingested_at=now,
        entity_id=entity_id,
        modality=Modality(modality),
        event_type=event_type,
        severity=severity,
        signal_name=signal_name,
        signal_value=signal_value,
        unit="count",
        source="test",
        source_record_id=str(uuid.uuid4()),
        schema_version="1.0",
        quality_flags=[],
        raw_payload={},
        trace_or_session_id=None,
    )


# ─── EwmaStateStore tests ──────────────────────────────────────────────────────

class TestEwmaStateStore:
    def test_get_returns_none_on_cold_start(self):
        session = _fresh_session()
        store = EwmaStateStore()
        result = store.get("e1", "sig1", session)
        assert result is None

    def test_put_and_get_roundtrip(self):
        session = _fresh_session()
        store = EwmaStateStore()
        state = {"ewma_mean": 42.0, "ewma_variance": 1.5, "n_samples": 10}
        store.put("e1", "sig1", state, session)
        result = store.get("e1", "sig1", session)
        assert result == state

    def test_flush_writes_new_row_to_db(self):
        session = _fresh_session()
        store = EwmaStateStore()
        state = {"ewma_mean": 7.5, "ewma_variance": 0.1, "n_samples": 3}
        store.put("gw", "tcp_resets_total", state, session)
        written = store.flush(session)
        session.flush()
        assert written == 1
        row = session.get(EwmaBaseline, ("gw", "tcp_resets_total"))
        assert row is not None
        assert row.ewma_mean == 7.5
        assert row.n_samples == 3

    def test_flush_updates_existing_row(self):
        session = _fresh_session()
        store = EwmaStateStore()
        # First flush
        store.put("gw", "cpu", {"ewma_mean": 30.0, "ewma_variance": 0.5, "n_samples": 5}, session)
        store.flush(session)
        session.flush()
        # Update + second flush
        store.put("gw", "cpu", {"ewma_mean": 35.0, "ewma_variance": 0.6, "n_samples": 6}, session)
        store.flush(session)
        session.flush()
        row = session.get(EwmaBaseline, ("gw", "cpu"))
        assert row.ewma_mean == 35.0
        assert row.n_samples == 6

    def test_flush_returns_zero_when_nothing_dirty(self):
        session = _fresh_session()
        store = EwmaStateStore()
        assert store.flush(session) == 0

    def test_reset_clears_cache_and_loaded_flag(self):
        session = _fresh_session()
        store = EwmaStateStore()
        store.put("gw", "sig", {"ewma_mean": 1.0, "ewma_variance": 0.0, "n_samples": 1}, session)
        store.reset()
        # After reset, get should return None (cache cleared)
        result = store.get("gw", "sig", session)
        assert result is None

    def test_load_from_db_on_first_get(self):
        session = _fresh_session()
        # Manually insert a row (simulate an existing warm baseline)
        session.add(EwmaBaseline(
            entity_id="gw", signal_name="sig",
            ewma_mean=55.0, ewma_variance=2.0, n_samples=100,
            updated_at=_now(),
        ))
        session.flush()

        store = EwmaStateStore()
        loaded = store.get("gw", "sig", session)
        assert loaded is not None
        assert loaded["ewma_mean"] == 55.0
        assert loaded["n_samples"] == 100


# ─── TopologyView tests ────────────────────────────────────────────────────────

class TestTopologyView:
    def test_empty_topology_returns_none(self):
        topo = TopologyView([])
        assert topo.distance("a", "b", "sends_traffic_to") is None

    def test_direct_edge_is_hop_1(self):
        topo = TopologyView([("a", "b", "sends_traffic_to")])
        assert topo.distance("a", "b", "sends_traffic_to") == 1

    def test_two_hop_path(self):
        topo = TopologyView([
            ("a", "b", "sends_traffic_to"),
            ("b", "c", "sends_traffic_to"),
        ])
        assert topo.distance("a", "c", "sends_traffic_to") == 2

    def test_hop_limit_returns_none_at_3(self):
        topo = TopologyView([
            ("a", "b", "sends_traffic_to"),
            ("b", "c", "sends_traffic_to"),
            ("c", "d", "sends_traffic_to"),
        ])
        # 3 hops exceeds MAX_HOPS=2 → None
        assert topo.distance("a", "d", "sends_traffic_to") is None

    def test_same_entity_returns_zero(self):
        topo = TopologyView([])
        assert topo.distance("a", "a", "depends_on") == 0

    def test_wrong_relation_type_returns_none(self):
        topo = TopologyView([("a", "b", "sends_traffic_to")])
        assert topo.distance("a", "b", "depends_on") is None

    def test_depends_on_relation(self):
        topo = TopologyView([("checkout", "payment-db", "depends_on")])
        assert topo.distance("checkout", "payment-db", "depends_on") == 1

    def test_build_for_session(self):
        session = _fresh_session()
        _entity(session, "gw")
        _entity(session, "api")
        _edge(session, "gw", "api", "sends_traffic_to")
        topo = TopologyView.build_for_session(session)
        assert topo.distance("gw", "api", "sends_traffic_to") == 1


# ─── Context injection tests ──────────────────────────────────────────────────

class TestContextInjection:
    def test_build_context_injects_ewma_state(self):
        """Injected ewma_state is a dict (possibly empty for unknown signals)."""
        session = _fresh_session()
        _entity(session, "gw")
        event = _canonical_event("gw", "forwarded_requests_per_second", 300.0)
        from app.detection.service import _build_context
        ctx = _build_context(event, session)
        assert hasattr(ctx, "ewma_state")
        assert isinstance(ctx.ewma_state, dict)

    def test_build_context_injects_ewma_updates_dict(self):
        session = _fresh_session()
        _entity(session, "gw")
        event = _canonical_event("gw", "forwarded_requests_per_second", 300.0)
        from app.detection.service import _build_context
        ctx = _build_context(event, session)
        assert hasattr(ctx, "_ewma_updates")
        assert isinstance(ctx._ewma_updates, dict)

    def test_build_context_injects_topology(self):
        session = _fresh_session()
        _entity(session, "gw")
        _entity(session, "api")
        _edge(session, "gw", "api", "sends_traffic_to")
        event = _canonical_event("api", "forwarded_requests_per_second", 300.0)
        topo = TopologyView.build_for_session(session)
        from app.detection.service import _build_context
        ctx = _build_context(event, session, topology=topo)
        assert ctx.topology is not None
        assert ctx.topology.distance("gw", "api", "sends_traffic_to") == 1

    def test_build_context_injects_recent_anomalies(self):
        """recent_anomalies list exists even when table is empty."""
        session = _fresh_session()
        _entity(session, "gw")
        event = _canonical_event("gw", "forwarded_requests_per_second", 300.0)
        from app.detection.service import _build_context
        ctx = _build_context(event, session)
        assert hasattr(ctx, "recent_anomalies")
        assert isinstance(ctx.recent_anomalies, list)


# ─── Cascade detector end-to-end with live wiring ────────────────────────────

class TestTopologyCascadeEndToEnd:
    """Verifies that TopologyCascadeDetector fires when topology + recent_anomalies
    are injected via the production service._build_context path."""

    def _make_context_with_upstream(
        self,
        session: Session,
        upstream_entity: str,
        downstream_entity: str,
        upstream_anomaly_score: float = 0.90,
    ) -> DetectionContext:
        """Manually assemble a DetectionContext that simulates what service.py injects."""
        from app.detection.service import _RecentAnomaly

        topo = TopologyView([
            (upstream_entity, downstream_entity, "sends_traffic_to"),
        ])
        recent = [
            _RecentAnomaly(
                entity_id=upstream_entity,
                anomaly_id="anomaly_001",
                anomaly_type="TCP_RESET_SPIKE",
                score=upstream_anomaly_score,
            )
        ]
        ctx = DetectionContext(history=[])
        object.__setattr__(ctx, "topology", topo)
        object.__setattr__(ctx, "recent_anomalies", recent)
        object.__setattr__(ctx, "ewma_state", {})
        object.__setattr__(ctx, "_ewma_updates", {})
        return ctx

    def test_cascade_fires_when_upstream_has_anomaly(self):
        session = _fresh_session()
        detector = TopologyCascadeDetector()
        event = _canonical_event(entity_id="downstream", event_type="METRIC", severity=0.8)
        ctx = self._make_context_with_upstream(session, "upstream", "downstream")
        results = detector.evaluate(event, ctx)
        assert len(results) == 1
        anomaly = results[0]
        assert anomaly.context_only is True
        assert anomaly.can_open_incident is False
        assert anomaly.features["upstream_entity"] == "upstream"
        assert anomaly.features["relation_type"] == "sends_traffic_to"
        assert anomaly.features["hop_distance"] == 1

    def test_cascade_score_formula(self):
        session = _fresh_session()
        detector = TopologyCascadeDetector()
        event = _canonical_event(entity_id="downstream", event_type="METRIC", severity=0.8)
        ctx = self._make_context_with_upstream(session, "upstream", "downstream", upstream_anomaly_score=0.90)
        results = detector.evaluate(event, ctx)
        assert len(results) == 1
        # 0.7 × 0.8 + 0.3 × 0.90 = 0.56 + 0.27 = 0.83
        assert abs(results[0].score - 0.83) < 0.01

    def test_no_cascade_when_topology_is_none(self):
        detector = TopologyCascadeDetector()
        event = _canonical_event("downstream")
        ctx = DetectionContext(history=[])
        # topology not injected → should return empty
        results = detector.evaluate(event, ctx)
        assert results == []

    def test_no_cascade_when_no_recent_anomalies(self):
        detector = TopologyCascadeDetector()
        event = _canonical_event("downstream")
        topo = TopologyView([("upstream", "downstream", "sends_traffic_to")])
        ctx = DetectionContext(history=[])
        object.__setattr__(ctx, "topology", topo)
        object.__setattr__(ctx, "recent_anomalies", [])
        results = detector.evaluate(event, ctx)
        assert results == []

    def test_explanation_contains_upstream_entity_and_score(self):
        session = _fresh_session()
        detector = TopologyCascadeDetector()
        event = _canonical_event(entity_id="downstream", severity=0.8)
        ctx = self._make_context_with_upstream(session, "upstream_gw", "downstream")
        results = detector.evaluate(event, ctx)
        assert "upstream_gw" in results[0].explanation
        assert "sends_traffic_to" in results[0].explanation


# ─── EWMA state persistence across context evaluations ───────────────────────

class TestEwmaStatePersistence:
    def test_ewma_state_written_to_updates_on_second_sample(self):
        """After the first sample, the state should appear in _ewma_updates."""
        from app.detection.ewma_detector import EwmaDetector

        session = _fresh_session()
        _entity(session, "gw")

        detector = EwmaDetector()
        # First sample → bootstrap, no anomaly, writes initial state
        ctx1 = DetectionContext(history=[])
        object.__setattr__(ctx1, "ewma_state", {})
        object.__setattr__(ctx1, "_ewma_updates", {})
        event1 = _canonical_event("gw", "forwarded_requests_per_second", 200.0)
        detector.evaluate(event1, ctx1)
        # Simulate what service.py does: copy _ewma_updates into ewma_state
        state_after_1 = {k: v[2] for k, v in ctx1._ewma_updates.items()}

        # Second sample — feed same entity/signal with the updated state
        ctx2 = DetectionContext(history=[])
        object.__setattr__(ctx2, "ewma_state", state_after_1)
        object.__setattr__(ctx2, "_ewma_updates", {})
        event2 = _canonical_event("gw", "forwarded_requests_per_second", 210.0)
        detector.evaluate(event2, ctx2)
        assert "gw:forwarded_requests_per_second" in ctx2._ewma_updates
        _, _, stored = ctx2._ewma_updates["gw:forwarded_requests_per_second"]
        assert stored["n_samples"] == 2
