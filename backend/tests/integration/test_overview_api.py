from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_session
from app.db import models
from app.main import app


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_recent_anomalies_include_entity_and_detector_identity():
    factory = _session_factory()
    now = datetime(2026, 7, 14, 9, 30, 30, tzinfo=timezone.utc)
    with factory() as session:
        session.add(
            models.Entity(
                id="api-gateway-01",
                name="API Gateway",
                entity_type="gateway",
                service="api-gateway",
                criticality="critical",
                metadata_json={},
            )
        )
        session.add(
            models.Event(
                id="evt_overview_001",
                timestamp=now,
                ingested_at=now,
                entity_id="api-gateway-01",
                modality="metric",
                event_type="FORWARDED_RPS",
                severity=0.0,
                signal_name="forwarded_rps",
                signal_value=7800.0,
                unit="requests/s",
                trace_or_session_id="scenario_gateway_rate_limit_001",
                source="simulator.prometheus",
                source_record_id="overview-001",
                schema_version="1.0",
                quality_flags=[],
                raw_payload={},
                status="accepted",
            )
        )
        session.add(
            models.Anomaly(
                id="ano_overview_001",
                event_id="evt_overview_001",
                detector_id="rolling_zscore_v1",
                type="FORWARDED_TRAFFIC_SPIKE",
                detected_at=now,
                score=0.94,
                threshold=0.75,
                context_only=False,
                can_open_incident=True,
                window_start=now,
                window_end=now,
                features={},
                explanation="Forwarded traffic exceeded its rolling baseline.",
            )
        )
        session.commit()

    def override_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/anomalies?limit=20")
        assert response.status_code == 200
        payload = response.json()
        assert payload["generated_at"].endswith("Z")
        assert payload["items"] == [
            {
                "anomaly_id": "ano_overview_001",
                "event_id": "evt_overview_001",
                "entity_id": "api-gateway-01",
                "source": "simulator.prometheus",
                "anomaly_type": "FORWARDED_TRAFFIC_SPIKE",
                "severity": 0.0,
                "score": 0.94,
                "detector_id": "rolling_zscore_v1",
                "detected_at": "2026-07-14T09:30:30Z",
                "context_only": False,
                "can_open_incident": True,
                "explanation": "Forwarded traffic exceeded its rolling baseline.",
            }
        ]
    finally:
        app.dependency_overrides.clear()


def test_simulator_status_exposes_six_typed_source_health_rows():
    with TestClient(app) as client:
        payload = client.get("/api/v1/simulator/status").json()
    assert payload["generated_at"].endswith("Z")
    assert [item["source_id"] for item in payload["source_health"]] == [
        "simulator.prometheus",
        "simulator.syslog",
        "simulator.alertmanager",
        "simulator.config_audit",
        "simulator.trace",
        "fixture.cmdb_topology",
    ]
    topology = payload["source_health"][-1]
    assert topology["status"] == "healthy"
    assert topology["fixture_version"] == "topology-1.2"
