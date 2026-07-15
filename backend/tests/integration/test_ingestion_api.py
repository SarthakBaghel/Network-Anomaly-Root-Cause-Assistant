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

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    metric = json.loads((FIXTURES / "valid_prometheus_sample.json").read_text(encoding="utf-8"))
    invalid = json.loads((FIXTURES / "invalid_syslog_record.json").read_text(encoding="utf-8"))
    try:
        created = client.post("/api/v1/events", json={"source": "simulator.prometheus", "record": metric})
        retry = client.post("/api/v1/events", json={"source": "simulator.prometheus", "record": metric})
        batch = client.post("/api/v1/events/batch", json={"events": [
            {"source": "simulator.syslog", "record": invalid},
            {"source": "unknown.source", "record": {}},
        ]})
        page = client.get("/api/v1/events", params={"limit": 1, "modality": "metric"})
        detail = client.get(f"/api/v1/events/{created.json()['event_id']}")
        quarantine = client.get("/api/v1/quarantine")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert retry.status_code == 200 and retry.json()["status"] == "idempotent"
    assert batch.status_code == 200
    assert [item["status"] for item in batch.json()["results"]] == ["quarantined", "quarantined"]
    assert page.status_code == 200 and len(page.json()["items"]) == 1
    assert detail.status_code == 200 and detail.json()["event_id"] == created.json()["event_id"]
    assert len(quarantine.json()["items"]) == 2
