from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import models
from app.orchestration.analysis_bundle import build_incident_analysis_bundle
from tests.support.rca_prerequisites import seed_golden_incident


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_bundle_is_ordered_detached_and_matches_incident_handoff() -> None:
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_golden_incident(session)
        bundle = build_incident_analysis_bundle(
            "inc_001",
            session,
            input_fingerprint=f"sha256:{'a' * 64}",
        )
        repeated = build_incident_analysis_bundle(
            "inc_001",
            session,
            input_fingerprint=f"sha256:{'a' * 64}",
        )

    frozen = json.loads(
        (FIXTURES / "golden_incident_bundle.json").read_text(encoding="utf-8")
    )
    assert {event.event_id for event in bundle.attached_events} == {
        row["event_id"] for row in frozen["attached_events"]
    }
    assert list(bundle.attached_events) == sorted(
        bundle.attached_events,
        key=lambda event: (event.timestamp, event.event_id),
    )
    assert [item.event.event_id for item in bundle.excluded_evaluations] == [
        row["event_id"] for row in frozen["excluded_events"]
    ]
    assert all(
        anomaly.event_id in {event.event_id for event in bundle.attached_events}
        for anomaly in bundle.anomalies
    )
    assert len(bundle.anomalies) == 10  # nine actionable + config context marker
    assert len(bundle.topology.nodes) == 5
    assert bundle.historical_matches[0].similarity == 0.5
    assert bundle.canonical_json() == repeated.canonical_json()


def test_excluded_event_never_enters_attached_partition() -> None:
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_golden_incident(session)
        bundle = build_incident_analysis_bundle("inc_001", session)

    attached = {event.event_id for event in bundle.attached_events}
    excluded = {item.event.event_id for item in bundle.excluded_evaluations}
    assert attached.isdisjoint(excluded)
    assert next(iter(bundle.excluded_evaluations)).event.entity_id == "auth-api-01"
