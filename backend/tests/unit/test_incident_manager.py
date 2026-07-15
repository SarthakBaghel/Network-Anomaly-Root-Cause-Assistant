from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.contracts import AnomalyRecord, CanonicalEvent
from app.db import models
from app.db.repositories import IncidentRepository
from app.incidents.manager import IncidentManager, serialize_incident_bundle
from app.topology.graph import get_topology_graph


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PROCESSING_ORDER = (
    "config-change-000001",
    "prom-forwarded_requests_per_second-0242",
    "prom-raw_ingress_requests_per_second-0241",
    "prom-active_connections_total-0243",
    "prom-connection_utilization-0244",
    "prom-tcp_resets_total-0245",
    "prom-tcp_retransmissions_total-0246",
    "alert-gateway-forwarded-0001",
    "prom-checkout_p95_latency_ms-0247",
    "log-payment-timeout-0001",
    "alert-checkout-error-0001",
    "prom-db_connection_utilization-0248",
    "log-auth-certificate-0001",
)


def _event_row(item: CanonicalEvent) -> models.Event:
    return models.Event(
        id=item.event_id,
        timestamp=item.timestamp,
        ingested_at=item.ingested_at,
        entity_id=item.entity_id,
        modality=item.modality.value,
        event_type=item.event_type,
        severity=item.severity,
        signal_name=item.signal_name,
        signal_value=item.signal_value,
        unit=item.unit,
        trace_or_session_id=item.trace_or_session_id,
        source=item.source,
        source_record_id=item.source_record_id,
        schema_version=item.schema_version,
        quality_flags=item.quality_flags,
        raw_payload=item.raw_payload,
        status="accepted",
    )


def _anomaly_row(item: AnomalyRecord) -> models.Anomaly:
    return models.Anomaly(
        id=item.anomaly_id,
        event_id=item.event_id,
        detector_id=item.detector_id,
        type=item.anomaly_type,
        detected_at=item.detected_at,
        score=item.score,
        threshold=item.threshold,
        context_only=item.context_only,
        can_open_incident=item.can_open_incident,
        window_start=item.window_start,
        window_end=item.window_end,
        features=item.features,
        explanation=item.explanation,
    )


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as database:
        topology = get_topology_graph()
        for node in topology.node_records:
            database.add(
                models.Entity(
                    id=node["id"],
                    name=node["name"],
                    entity_type=node["entity_type"],
                    service=node["service"],
                    criticality=node["criticality"],
                    metadata_json=node.get("metadata", {}),
                )
            )
        event_records = [
            CanonicalEvent.model_validate_json(line)
            for line in (FIXTURES / "golden_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        database.add_all(_event_row(item) for item in event_records)
        anomaly_payload = json.loads(
            (FIXTURES / "golden_anomalies.json").read_text(encoding="utf-8")
        )
        database.add_all(
            _anomaly_row(AnomalyRecord.model_validate(item))
            for item in anomaly_payload["anomalies"]
            + anomaly_payload["context_markers"]
        )
        database.commit()
        yield database
    engine.dispose()


def _events_by_source(session: Session) -> dict[str, models.Event]:
    return {
        event.source_record_id: event
        for event in session.execute(select(models.Event)).scalars()
        if event.source_record_id in PROCESSING_ORDER
    }


def _anomalies_by_event(session: Session) -> dict[str, list[models.Anomaly]]:
    grouped: dict[str, list[models.Anomaly]] = {}
    for anomaly in session.execute(select(models.Anomaly)).scalars():
        grouped.setdefault(anomaly.event_id, []).append(anomaly)
    return grouped


def _run_golden_scenario(session: Session) -> models.Incident:
    events = _events_by_source(session)
    anomalies = _anomalies_by_event(session)
    manager = IncidentManager(incident_id_factory=lambda: "inc_001")

    context_result = manager.process_anomalies(
        anomalies[events[PROCESSING_ORDER[0]].id],
        events[PROCESSING_ORDER[0]],
        session,
    )
    assert context_result is None
    assert session.execute(select(models.Incident)).scalar_one_or_none() is None

    current: models.Incident | None = None
    for source_record_id in PROCESSING_ORDER[1:]:
        event = events[source_record_id]
        result = manager.process_anomalies(
            anomalies.get(event.id, []), event, session
        )
        if result is not None:
            current = result
    assert current is not None
    return current


def test_lookback_attachment_exclusion_and_conflicting_evidence(
    session: Session,
) -> None:
    incident = _run_golden_scenario(session)
    repository = IncidentRepository(session)
    session.refresh(incident)

    assert incident.started_at.replace(tzinfo=None) == datetime.fromisoformat(
        "2026-07-14T09:30:00"
    )
    assert incident.last_event_at.replace(tzinfo=None) == datetime.fromisoformat(
        "2026-07-14T09:31:40"
    )
    assert incident.anomaly_count == 9

    events = _events_by_source(session)
    config = repository.get_evaluation(
        incident.id, events["config-change-000001"].id
    )
    raw_ingress = repository.get_evaluation(
        incident.id, events["prom-raw_ingress_requests_per_second-0241"].id
    )
    normal_database = repository.get_evaluation(
        incident.id, events["prom-db_connection_utilization-0248"].id
    )
    auth = repository.get_evaluation(
        incident.id, events["log-auth-certificate-0001"].id
    )

    assert config is not None and config.decision == "attached"
    assert "WITHIN_60_SECONDS" in config.attachment_reasons
    assert raw_ingress is not None and raw_ingress.decision == "attached"
    assert normal_database is not None and normal_database.decision == "attached"
    assert "CONFLICTING_DB_EVIDENCE" in normal_database.attachment_reasons
    assert auth is not None and auth.decision == "excluded"
    assert auth.attachment_score <= 0
    assert auth.attachment_reasons == [
        "INCOMPATIBLE_MAINTENANCE_SYMPTOM",
        "EXPLICIT_DIFFERENT_TRACE",
    ]
    assert not repository.is_event_attached(incident.id, auth.event_id)


def test_runtime_incident_bundle_matches_frozen_handoff(session: Session) -> None:
    incident = _run_golden_scenario(session)
    session.add(
        models.AnalysisRun(
            id="run_007",
            incident_id=incident.id,
            revision=7,
            status="current",
            trigger_event_id=None,
            input_fingerprint="fixture-fingerprint",
            algorithm_version="test",
            created_at=datetime.fromisoformat("2026-07-14T09:32:01+00:00"),
            completed_at=datetime.fromisoformat("2026-07-14T09:32:02+00:00"),
            failure_reason=None,
        )
    )
    session.add(
        models.Hypothesis(
            id="hyp_001",
            analysis_run_id="run_007",
            incident_id=incident.id,
            type="configuration_regression",
            candidate_entity_id="api-gateway-01",
            rank=1,
            evidence_score=92.1,
            coverage={"available": 5, "expected": 6},
            factor_scores={},
            summary="Frozen top hypothesis",
        )
    )
    session.flush()
    IncidentRepository(session).set_current_analysis_run(
        incident.id, "run_007", "hyp_001"
    )

    expected = json.loads(
        (FIXTURES / "golden_incident_bundle.json").read_text(encoding="utf-8")
    )
    assert serialize_incident_bundle(session, incident.id) == expected


def test_context_marker_and_threshold_equal_anomaly_cannot_open(
    session: Session,
) -> None:
    events = _events_by_source(session)
    context = _anomalies_by_event(session)[events["config-change-000001"].id][0]
    threshold_anomaly = models.Anomaly(
        id="ano_at_open_threshold",
        event_id=events["prom-forwarded_requests_per_second-0242"].id,
        detector_id="test",
        type="TEST_THRESHOLD",
        detected_at=events["prom-forwarded_requests_per_second-0242"].timestamp,
        score=0.75,
        threshold=0.75,
        context_only=False,
        can_open_incident=True,
        window_start=events["config-change-000001"].timestamp,
        window_end=events["prom-forwarded_requests_per_second-0242"].timestamp,
        features={},
        explanation="Exactly equal to the opening threshold",
    )
    manager = IncidentManager(incident_id_factory=lambda: "must_not_open")

    assert manager.process_anomalies(
        [context], events["config-change-000001"], session
    ) is None
    assert manager.process_anomalies(
        [threshold_anomaly],
        events["prom-forwarded_requests_per_second-0242"],
        session,
    ) is None
    assert session.execute(select(models.Incident)).scalar_one_or_none() is None
