from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import models
from app.ingestion.pipeline import IngestionPipeline


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "source_adapters"


def test_only_new_accepted_representatives_enter_orchestration(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    published: list[str] = []

    def record_publish(_publisher, event) -> None:
        published.append(event.event_id)

    monkeypatch.setattr(
        "app.orchestration.publisher.OrchestrationPublisher.publish",
        record_publish,
    )

    raw = json.loads(
        (FIXTURES / "valid_prometheus_sample.json").read_text(encoding="utf-8")
    )
    with Session(engine) as session:
        session.add(
            models.Entity(
                id="api-gateway-01",
                name="api-gateway-01",
                entity_type="gateway",
                service="gateway",
                criticality="tier-1",
                metadata_json={},
            )
        )
        session.flush()
        pipeline = IngestionPipeline()

        accepted = pipeline.ingest(
            source="simulator.prometheus",
            raw=raw,
            request_id="req-new",
            session=session,
        )
        retry = pipeline.ingest(
            source="simulator.prometheus",
            raw=raw,
            request_id="req-retry",
            session=session,
        )
        quarantined = pipeline.ingest(
            source="unknown.source",
            raw={},
            request_id="req-invalid",
            session=session,
        )

    assert accepted.analysis_state == "processed"
    assert retry.reason_codes == ["IDEMPOTENT_RETRY"]
    assert quarantined.status == "quarantined"
    assert published == [accepted.event_id]
