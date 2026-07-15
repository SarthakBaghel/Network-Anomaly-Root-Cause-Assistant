from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

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


def test_golden_replay_persists_nine_actionable_anomalies_and_one_marker() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        pipeline = IngestionPipeline(session)
        records = [record for group in [*baseline_groups(), *scenario_groups()] for record in group.records]
        results = pipeline.ingest_many(list(records))
        anomalies = list(session.scalars(select(Anomaly).order_by(Anomaly.window_end, Anomaly.id)))
        assert all(result.status == "created" for result in results)
        assert len([item for item in anomalies if item.can_open_incident]) == 9
        assert len([item for item in anomalies if item.context_only]) == 1
        assert not any(item.event_id.endswith("1d99bedd627abe8ef1dca5d6") for item in anomalies)


def test_metrics_never_collapse_and_exact_retry_is_idempotent() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    raw = json.loads((FIXTURES / "valid_prometheus_sample.json").read_text(encoding="utf-8"))
    second = json.loads(json.dumps(raw))
    second["sample_id"] = "metric-second"
    with Session(engine) as session:
        pipeline = IngestionPipeline(session)
        statuses = [
            pipeline.ingest("simulator.prometheus", raw).status,
            pipeline.ingest("simulator.prometheus", raw).status,
            pipeline.ingest("simulator.prometheus", second).status,
        ]
        assert statuses == ["created", "idempotent", "created"]
        assert session.query(Event).count() == 2
        assert session.query(CollapsedEventGroup).count() == 0
