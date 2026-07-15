from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.contracts import CanonicalEvent
from app.db.models import Base, CollapsedEventGroup, Event, QuarantinedEvent
from app.ingestion.adapters import ADAPTERS
from app.ingestion.pipeline import IngestionPipeline
from app.simulator.timeline import baseline_groups, scenario_groups


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SOURCES = FIXTURES / "source_adapters"


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


@pytest.mark.parametrize(
    ("source", "filename", "expected"),
    [
        ("simulator.prometheus", "valid_prometheus_sample.json", {"entity_id": "api-gateway-01", "event_type": "FORWARDED_REQUEST_RATE", "severity": 0.0, "signal_name": "forwarded_requests_per_second", "signal_value": 7800.0, "unit": "requests/s"}),
        ("simulator.syslog", "valid_syslog_record.json", {"entity_id": "payment-api-01", "event_type": "UPSTREAM_CONNECTION_TIMEOUT", "severity": 0.88, "trace_or_session_id": "scenario_gateway_rate_limit_001"}),
        ("simulator.alertmanager", "valid_alertmanager_alert.json", {"entity_id": "api-gateway-01", "event_type": "HIGH_FORWARDED_REQUEST_AND_CONNECTION_RATE", "severity": 0.95}),
        ("simulator.config_audit", "valid_config_audit.json", {"entity_id": "api-gateway-01", "event_type": "CONFIG_VALUE_CHANGED", "severity": 0.0}),
    ],
)
def test_adapters_map_exact_canonical_values(source: str, filename: str, expected: dict) -> None:
    raw = json.loads((SOURCES / filename).read_text(encoding="utf-8"))
    event = ADAPTERS[source].adapt(raw)
    for field, value in expected.items():
        assert getattr(event, field) == value
    if source == "simulator.config_audit":
        assert event.raw_payload["context_only"] is True


@pytest.mark.parametrize(
    ("source", "filename", "reason"),
    [
        ("simulator.prometheus", "invalid_prometheus_sample.json", "PROMETHEUS_MAPPING_ERROR"),
        ("simulator.syslog", "invalid_syslog_record.json", "SYSLOG_MAPPING_ERROR"),
        ("simulator.alertmanager", "invalid_alertmanager_alert.json", "ALERTMANAGER_MAPPING_ERROR"),
        ("simulator.config_audit", "invalid_config_audit.json", "CONFIG_AUDIT_MAPPING_ERROR"),
    ],
)
def test_invalid_adapter_records_are_quarantined_with_reason(session: Session, source: str, filename: str, reason: str) -> None:
    raw = json.loads((SOURCES / filename).read_text(encoding="utf-8"))
    result = IngestionPipeline(session).ingest(source, raw)
    assert result.status == "quarantined"
    assert result.reason_codes == [reason]
    assert session.scalar(select(QuarantinedEvent)).validation_errors[0]["reason_code"] == reason


def test_alert_storm_collapses_and_preserves_bounds(session: Session) -> None:
    raw = json.loads((SOURCES / "valid_alertmanager_alert.json").read_text(encoding="utf-8"))
    first = IngestionPipeline(session).ingest("simulator.alertmanager", raw)
    duplicate = json.loads(json.dumps(raw))
    duplicate["fingerprint"] = "alert-distinct-delivery"
    second = IngestionPipeline(session).ingest("simulator.alertmanager", duplicate)
    group = session.scalar(select(CollapsedEventGroup))
    assert first.status == "created"
    assert second.status == "collapsed"
    assert group.event_count == 2
    assert group.first_seen == group.last_seen
    assert group.representative_event_id == first.event_id


def test_metric_samples_never_collapse_and_retry_is_idempotent(session: Session) -> None:
    raw = json.loads((SOURCES / "valid_prometheus_sample.json").read_text(encoding="utf-8"))
    pipeline = IngestionPipeline(session)
    first = pipeline.ingest("simulator.prometheus", raw)
    retry = pipeline.ingest("simulator.prometheus", raw)
    other = json.loads(json.dumps(raw))
    other["sample_id"] = "another-metric-sample"
    third = pipeline.ingest("simulator.prometheus", other)
    assert [first.status, retry.status, third.status] == ["created", "idempotent", "created"]
    assert session.query(Event).count() == 2
    assert session.query(CollapsedEventGroup).count() == 0


def test_recursive_redaction_marks_quality_flag(session: Session) -> None:
    raw = json.loads((SOURCES / "valid_config_audit.json").read_text(encoding="utf-8"))
    raw["details"] = {"authorization": "Bearer abc", "nested": [{"api_key": "key"}]}
    result = IngestionPipeline(session).ingest("simulator.config_audit", raw)
    event = session.get(Event, result.event_id)
    assert event.raw_payload["details"] == {"authorization": "[REDACTED]", "nested": [{"api_key": "[REDACTED]"}]}
    assert "RAW_PAYLOAD_REDACTED" in event.quality_flags


def test_batch_publishes_accepted_events_once(session: Session) -> None:
    class Publisher:
        def __init__(self) -> None:
            self.single_calls = 0
            self.batches: list[list[CanonicalEvent]] = []

        def publish(self, event: CanonicalEvent) -> None:
            self.single_calls += 1

        def publish_batch(self, events: list[CanonicalEvent]) -> None:
            self.batches.append(events)

    publisher = Publisher()
    metric = json.loads((SOURCES / "valid_prometheus_sample.json").read_text(encoding="utf-8"))
    second = json.loads(json.dumps(metric))
    second["sample_id"] = "batch-metric-two"
    results = IngestionPipeline(session, publisher=publisher).ingest_many([
        ("simulator.prometheus", metric),
        ("simulator.prometheus", second),
        ("unknown.source", {}),
    ])
    assert [result.status for result in results] == ["created", "created", "quarantined"]
    assert publisher.single_calls == 0
    assert len(publisher.batches) == 1 and len(publisher.batches[0]) == 2


def test_raw_reference_bundle_replays_to_golden_events() -> None:
    actual: list[CanonicalEvent] = []
    for group in [*baseline_groups(), *scenario_groups()]:
        for source, raw in group.records:
            actual.append(ADAPTERS[source].adapt(raw))
    expected_lines = (FIXTURES / "golden_events.jsonl").read_text(encoding="utf-8").splitlines()
    expected = [CanonicalEvent.model_validate_json(line) for line in expected_lines]
    key = lambda event: (event.ingested_at, event.event_id)
    assert [event.model_dump() for event in sorted(actual, key=key)] == [event.model_dump() for event in sorted(expected, key=key)]
