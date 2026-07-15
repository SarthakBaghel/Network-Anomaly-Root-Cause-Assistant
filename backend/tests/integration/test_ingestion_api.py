from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_session
from app.main import app


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "source_adapters"


def test_ingestion_status_codes_batch_partial_success_and_cursor(monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    # Seed required entities
    from app.db.models import Entity
    with Session(engine) as seed_session:
        for entity_id, entity_type, service in [
            ("api-gateway-01", "gateway", "gateway"),
            ("payment-api-01", "api", "payment"),
        ]:
            seed_session.add(Entity(id=entity_id, name=entity_id, entity_type=entity_type,
                                    service=service, criticality="tier-1", metadata_json={}))
        seed_session.commit()

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    metric = json.loads((FIXTURES / "valid_prometheus_sample.json").read_text(encoding="utf-8"))
    invalid = json.loads((FIXTURES / "invalid_syslog_record.json").read_text(encoding="utf-8"))
    published_batches: list[list[str]] = []

    def record_batch(_publisher, events) -> None:
        published_batches.append([event.event_id for event in events])

    monkeypatch.setattr(
        "app.orchestration.publisher.OrchestrationPublisher.publish_batch",
        record_batch,
    )
    try:
        # New API uses 'raw' field name (not 'record')
        created = client.post("/api/v1/events", json={"source": "simulator.prometheus", "raw": metric})
        retry = client.post("/api/v1/events", json={"source": "simulator.prometheus", "raw": metric})
        batch_metric = json.loads(json.dumps(metric))
        batch_metric["sample_id"] = "batch-metric-two"
        batch = client.post("/api/v1/events/batch", json=[
            {"source": "simulator.prometheus", "raw": batch_metric},
            {"source": "simulator.syslog", "raw": invalid},
            {"source": "unknown.source", "raw": {}},
        ])
        first_page = client.get("/api/v1/events", params={"limit": 1, "modality": "metric"})
        cursor = first_page.json()["next_cursor"]
        second_page = client.get(
            "/api/v1/events",
            params={"limit": 1, "modality": "metric", "cursor": cursor},
        )
        mismatched_cursor = client.get(
            "/api/v1/events",
            params={"limit": 1, "entity_id": "api-gateway-01", "cursor": cursor},
        )
        malformed_cursor = client.get("/api/v1/events", params={"cursor": "not-a-cursor"})
        event_id = created.json().get("event_id")
        detail = client.get(f"/api/v1/events/{event_id}") if event_id else None
        quarantine = client.get("/api/v1/quarantine")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code in (200, 201), f"Expected 200/201, got {created.status_code}: {created.text}"
    assert created.json()["status"] == "accepted"
    assert retry.status_code == 200
    assert batch.status_code == 200
    assert [item["status"] for item in batch.json()["results"]] == [
        "accepted",
        "quarantined",
        "quarantined",
    ]
    assert batch.json()["results"][0]["analysis_state"] == "processed"
    assert len(published_batches) == 1 and len(published_batches[0]) == 1
    assert first_page.status_code == 200 and len(first_page.json()["items"]) == 1
    assert second_page.status_code == 200 and len(second_page.json()["items"]) == 1
    assert first_page.json()["items"][0]["event_id"] != second_page.json()["items"][0]["event_id"]
    assert mismatched_cursor.status_code == 400
    assert mismatched_cursor.json()["error"]["code"] == "INVALID_CURSOR"
    assert malformed_cursor.status_code == 400
    event_id = created.json().get("event_id")
    if detail and event_id:
        assert detail.status_code == 200 and detail.json()["event_id"] == event_id
    assert len(quarantine.json()["items"]) >= 2


def test_batch_rejects_more_than_one_hundred_items() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/events/batch",
        json=[{"source": "unknown.source", "raw": {}} for _ in range(101)],
    )
    assert response.status_code == 413
