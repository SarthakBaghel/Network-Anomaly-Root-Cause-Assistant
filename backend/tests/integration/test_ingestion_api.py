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


def test_ingestion_status_codes_batch_partial_success_and_cursor() -> None:
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
    try:
        # New API uses 'raw' field name (not 'record')
        created = client.post("/api/v1/events", json={"source": "simulator.prometheus", "raw": metric})
        retry = client.post("/api/v1/events", json={"source": "simulator.prometheus", "raw": metric})
        batch = client.post("/api/v1/events/batch", json=[  # list of RawIngestionRequest
            {"source": "simulator.syslog", "raw": invalid},
            {"source": "unknown.source", "raw": {}},
        ])
        page = client.get("/api/v1/events", params={"limit": 1, "modality": "metric"})
        event_id = created.json().get("event_id")
        detail = client.get(f"/api/v1/events/{event_id}") if event_id else None
        quarantine = client.get("/api/v1/quarantine")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code in (200, 201), f"Expected 200/201, got {created.status_code}: {created.text}"
    assert created.json()["status"] == "accepted"
    assert retry.status_code == 200
    assert batch.status_code == 200
    assert all(item["status"] == "quarantined" for item in batch.json()["results"])
    # GET /events returns a raw list (not dict with 'items')
    assert page.status_code == 200 and len(page.json()) >= 1
    event_id = created.json().get("event_id")
    if detail and event_id:
        assert detail.status_code == 200 and detail.json()["event_id"] == event_id
    assert len(quarantine.json()["items"]) >= 2
