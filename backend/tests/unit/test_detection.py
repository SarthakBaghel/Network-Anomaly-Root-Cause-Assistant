from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import uuid as _uuid
from app.contracts import CanonicalEvent
from app.db.models import Anomaly, Base, CollapsedEventGroup, Event
from app.detection import ConfigChangeMarker, DetectionContext, RollingZscoreDetector, metric_score
from app.ingestion.pipeline import IngestionPipeline
from app.simulator.timeline import baseline_groups, scenario_groups


UTC = timezone.utc
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "source_adapters"


def metric_event(identifier: str, timestamp: datetime, value: float) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=f"evt_{identifier}", timestamp=timestamp, ingested_at=timestamp,
        entity_id="api-gateway-01", modality="metric", event_type="FORWARDED_REQUEST_RATE",
        severity=0.0, signal_name="forwarded_requests_per_second", signal_value=value,
        unit="requests/s", source="test.prometheus", source_record_id=identifier,
        schema_version="1.0", raw_payload={},
    )


def test_zscore_requires_minimum_baseline_and_fires_after_threshold() -> None:
    detector = RollingZscoreDetector()
    observed_at = datetime(2026, 7, 14, 9, 30, 30, tzinfo=UTC)
    event = metric_event("observed", observed_at, 7800.0)
    nineteen = [metric_event(str(index), observed_at - timedelta(seconds=10 * (20 - index)), 2400.0) for index in range(19)]
    assert detector.evaluate(event, DetectionContext(history=nineteen)) == []
    twenty = [*nineteen, metric_event("19", observed_at - timedelta(seconds=10), 2400.0)]
    anomaly = detector.evaluate(event, DetectionContext(history=twenty))[0]
    assert anomaly.anomaly_type == "FORWARDED_TRAFFIC_SPIKE"
    assert anomaly.score == 1.0

    varied = [
        metric_event(f"varied-{index}", observed_at - timedelta(seconds=10 * (20 - index)), 2300.0 if index % 2 else 2500.0)
        for index in range(20)
    ]
    z_only_event = metric_event("z-only", observed_at, 5000.0)
    z_only = detector.evaluate(
        z_only_event,
        DetectionContext(history=varied, safety_thresholds={"forwarded_requests_per_second": 10000.0}),
    )[0]
    assert z_only.features["z_score"] > 3.0
    assert z_only.features["observed"] < z_only.features["safety_threshold"]


def test_golden_score_formula_rounds_half_up_to_point_91() -> None:
    assert metric_score(4.25, observed=7800.0, safety_threshold=5000.0) == 0.91


def test_config_marker_is_context_only_and_cannot_open_incident() -> None:
    timestamp = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
    event = CanonicalEvent(
        event_id="evt_config", timestamp=timestamp, ingested_at=timestamp,
        entity_id="api-gateway-01", modality="config_change", event_type="CONFIG_VALUE_CHANGED",
        severity=0.0, source="test.config", source_record_id="change-1", schema_version="1.0",
        raw_payload={"change_ticket": "CHG-DEMO-001"},
    )
    marker = ConfigChangeMarker().evaluate(event, DetectionContext())[0]
    assert marker.context_only is True
    assert marker.can_open_incident is False
    assert marker.score == 0.0


def _seed_entities(session: Session) -> None:
    from app.db.models import Entity
    for entity_id, entity_type, service in [
        ("api-gateway-01", "gateway", "gateway"),
        ("payment-api-01", "api", "payment"),
        ("checkout-api-01", "api", "checkout"),
        ("auth-api-01", "api", "auth"),
        ("payment-db-01", "database", "payment"),
    ]:
        session.add(Entity(id=entity_id, name=entity_id, entity_type=entity_type,
                           service=service, criticality="tier-1", metadata_json={}))
    session.flush()


def _seed_topology(session: Session) -> None:
    import json
    from pathlib import Path
    from app.db.models import TopologyEdge
    topo_path = Path(__file__).resolve().parents[2] / "app" / "fixtures" / "topology.json"
    topo = json.loads(topo_path.read_text(encoding="utf-8"))
    for i, edge in enumerate(topo.get("edges", [])):
        session.add(
            TopologyEdge(
                id=f"edge_{i:04d}",
                source_entity_id=edge["source"],
                target_entity_id=edge["target"],
                relation_type=edge["relation_type"],
                relationship=edge.get("relationship", edge["relation_type"]),
                active_from=None,
                active_to=None,
            )
        )
    session.flush()


def test_golden_replay_persists_fifteen_actionable_and_three_context_anomalies() -> None:
    """Golden scenario replay — production-wired counts.

    After EWMA + topology context injection:
      - EWMA detector fires on 6 of the 9 metric spike events (needs >5 warmup samples)
        producing 6 additional actionable anomalies alongside the z-score anomalies
      - TopologyCascadeDetector now fires context_only signals on downstream events
        consistent with upstream gateway anomalies (2 cascade signals + 1 config marker)

    Previous counts (pre-wiring):
      - 9 actionable (rolling_zscore + log_rule + alert_severity)
      - 1 context_only (config_change marker)

    Current counts (production-wired):
      - 15 actionable (rolling_zscore×9 + ewma×6)
      - 3 context_only (config_change marker + 2 topology_cascade)
    """
    from app.detection.service import DetectionPublisher
    from app.db.models import Event as EventModel
    from app.ingestion.pipeline import event_to_contract

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_entities(session)
        _seed_topology(session)
        pipeline = IngestionPipeline()

        publisher = DetectionPublisher(session)
        records = [record for group in [*baseline_groups(), *scenario_groups()] for record in group.records]
        for source, raw in records:
            result = pipeline.ingest(source=source, raw=raw, request_id=str(_uuid.uuid4()), session=session)
            # Run detection on each accepted event (P4/P5 separation of ingestion and detection)
            if result.status == "accepted" and result.event_id:
                event_row = session.get(EventModel, result.event_id)
                if event_row:
                    publisher.publish(event_to_contract(event_row))
        session.flush()
        anomalies = list(session.scalars(select(Anomaly).order_by(Anomaly.window_end, Anomaly.id)))
        assert len([item for item in anomalies if item.can_open_incident]) == 15
        assert len([item for item in anomalies if item.context_only]) == 3
        assert not any(item.event_id.endswith("1d99bedd627abe8ef1dca5d6") for item in anomalies)


def test_person3_detector_replay_matches_golden_anomaly_manifest_exactly() -> None:
    from app.contracts import AnomalyRecord
    from app.detection import AlertSeverityDetector, LogRuleDetector

    events = []
    for group in [*baseline_groups(), *scenario_groups()]:
        for source, raw in group.records:
            from app.ingestion.adapters import ADAPTERS

            events.append(ADAPTERS[source].adapt(raw))
    events.sort(key=lambda item: (item.timestamp, item.event_id))

    detectors = (
        RollingZscoreDetector(),
        LogRuleDetector(),
        AlertSeverityDetector(),
        ConfigChangeMarker(),
    )
    actual = []
    history = []
    for event in events:
        context = DetectionContext(history=list(history))
        for detector in detectors:
            actual.extend(detector.evaluate(event, context))
        history.append(event)

    manifest = json.loads(
        (FIXTURES.parent / "golden_anomalies.json").read_text(encoding="utf-8")
    )
    expected = [
        AnomalyRecord.model_validate(item)
        for item in [*manifest["anomalies"], *manifest["context_markers"]]
    ]
    key = lambda item: (item.window_end, item.event_id, item.detector_id)
    assert [item.model_dump() for item in sorted(actual, key=key)] == [
        item.model_dump() for item in sorted(expected, key=key)
    ]




def test_metrics_never_collapse_and_exact_retry_is_idempotent() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    raw = json.loads((FIXTURES / "valid_prometheus_sample.json").read_text(encoding="utf-8"))
    second = json.loads(json.dumps(raw))
    second["sample_id"] = "metric-second"
    with Session(engine) as session:
        _seed_entities(session)
        pipeline = IngestionPipeline()
        r1 = pipeline.ingest(source="simulator.prometheus", raw=raw, request_id=str(_uuid.uuid4()), session=session)
        r2 = pipeline.ingest(source="simulator.prometheus", raw=raw, request_id=str(_uuid.uuid4()), session=session)
        r3 = pipeline.ingest(source="simulator.prometheus", raw=second, request_id=str(_uuid.uuid4()), session=session)
        # Prometheus metrics use source_record_id dedup; retry is accepted with IDEMPOTENT_RETRY
        assert r1.status == "accepted"
        assert r2.status == "accepted" and "IDEMPOTENT_RETRY" in r2.reason_codes
        assert r3.status == "accepted"
        # first + second (different sample_id) both persisted
        assert session.query(Event).count() == 2
        assert session.query(CollapsedEventGroup).count() == 0
