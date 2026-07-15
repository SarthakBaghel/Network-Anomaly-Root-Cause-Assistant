from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_session
from app.db import models
from app.main import app


ROOT = Path(__file__).resolve().parents[3]
SOURCE_FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "source_adapters"


def test_event_api_exposes_quarantine_and_collapse_outcomes() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
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
        session.commit()

    def override_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    invalid = json.loads(
        (SOURCE_FIXTURES / "invalid_alertmanager_alert.json").read_text()
    )
    invalid["api_token"] = "must-be-redacted"
    valid = json.loads(
        (SOURCE_FIXTURES / "valid_alertmanager_alert.json").read_text()
    )
    duplicate = dict(valid)
    duplicate["fingerprint"] = "alert-gateway-forwarded-api-duplicate"

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        quarantined = client.post(
            "/api/v1/events",
            json={
                "source": "simulator.alertmanager",
                "raw": invalid,
                "request_id": "req_api_invalid",
            },
        )
        accepted = client.post(
            "/api/v1/events",
            json={
                "source": "simulator.alertmanager",
                "raw": valid,
                "request_id": "req_api_first",
            },
        )
        collapsed = client.post(
            "/api/v1/events",
            json={
                "source": "simulator.alertmanager",
                "raw": duplicate,
                "request_id": "req_api_duplicate",
            },
        )
        quarantine_view = client.get("/api/v1/quarantine")

        assert quarantined.status_code == 202
        assert quarantined.json()["status"] == "quarantined"
        assert accepted.status_code == 201
        assert accepted.json()["status"] == "accepted"
        assert collapsed.status_code == 200
        assert collapsed.json()["status"] == "collapsed"
        assert (
            collapsed.json()["representative_event_id"]
            == accepted.json()["event_id"]
        )
        assert quarantine_view.status_code == 200
        assert quarantine_view.json()["items"][0]["raw_payload"]["api_token"] == "[REDACTED]"
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()
