from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.contracts import AnomalyRecord, CanonicalEvent
from app.db import models
from app.incidents.manager import IncidentManager, serialize_incident_bundle
from app.topology.graph import get_topology_graph
from tests.support.rca_prerequisites import _anomaly_row, _event_row


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_runtime_incident_manager_reproduces_golden_bundle_exactly() -> None:
    events = [
        CanonicalEvent.model_validate_json(line)
        for line in (FIXTURES / "golden_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    anomaly_payload = json.loads(
        (FIXTURES / "golden_anomalies.json").read_text(encoding="utf-8")
    )
    anomalies = [
        AnomalyRecord.model_validate(item)
        for item in (
            anomaly_payload["anomalies"]
            + anomaly_payload["context_markers"]
        )
    ]
    anomaly_ids_by_event: dict[str, list[str]] = {}
    for anomaly in anomalies:
        anomaly_ids_by_event.setdefault(anomaly.event_id, []).append(
            anomaly.anomaly_id
        )

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            for node in get_topology_graph().node_records:
                session.add(
                    models.Entity(
                        id=node["id"],
                        name=node["name"],
                        entity_type=node["entity_type"],
                        service=node["service"],
                        criticality=node["criticality"],
                        metadata_json=node.get("metadata", {}),
                    )
                )
            session.add_all(_event_row(item) for item in events)
            session.add_all(_anomaly_row(item) for item in anomalies)
            session.flush()

            manager = IncidentManager(incident_id_factory=lambda: "inc_001")
            incident = None
            for event in sorted(events, key=lambda item: (item.timestamp, item.event_id)):
                event_row = session.get(models.Event, event.event_id)
                assert event_row is not None
                anomaly_rows = [
                    session.get(models.Anomaly, anomaly_id)
                    for anomaly_id in anomaly_ids_by_event.get(event.event_id, ())
                ]
                result = manager.process_anomalies(
                    [row for row in anomaly_rows if row is not None],
                    event_row,
                    session,
                )
                if result is not None:
                    incident = result

            assert incident is not None
            expected = json.loads(
                (FIXTURES / "golden_incident_bundle.json").read_text(
                    encoding="utf-8"
                )
            )

            # Analysis publication owns these three fields. Pin its frozen
            # handoff identities so this test can compare the complete P4
            # serialization while exercising real incident attachment logic.
            incident.status = expected["incident"]["status"]
            incident.current_analysis_run_id = expected["incident"][
                "current_analysis_run_id"
            ]
            incident.top_hypothesis_id = expected["incident"][
                "top_hypothesis_id"
            ]
            with session.no_autoflush:
                actual = serialize_incident_bundle(session, incident.id)

            assert actual == expected
    finally:
        engine.dispose()
