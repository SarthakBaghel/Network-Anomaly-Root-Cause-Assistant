from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit import AUDIT_ACTION_CODES, AuditWrite
from app.db import models
from app.db.repositories import AuditRepository
from app.ingestion.pipeline import IngestionPipeline


ROOT = Path(__file__).resolve().parents[3]
ADAPTER_FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "source_adapters"


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _audit_write(action: str) -> AuditWrite:
    run_scoped = action in {
        "ANALYSIS_PUBLISHED",
        "EXPLANATION_FALLBACK_USED",
        "REVIEW_CONFIRMED",
        "REVIEW_REJECTED",
        "REVIEW_EVIDENCE_REQUESTED",
        "INCIDENT_STATUS_CHANGED",
    }
    incident_scoped = run_scoped or action in {
        "INCIDENT_OPENED",
        "EVENT_ATTACHED",
        "EVENT_EXCLUDED",
        "PIPELINE_STAGE_FAILED",
    }
    return AuditWrite(
        action=action,
        actor_type="system",
        actor_id="test",
        object_type="incident" if incident_scoped else "system",
        object_id="inc_001" if incident_scoped else "demo",
        incident_id="inc_001" if incident_scoped else None,
        analysis_run_id="run_007" if run_scoped else None,
        analysis_revision=7 if run_scoped else None,
        request_id=f"req_{action.lower()}",
        reason_codes=["TEST_REASON"],
        previous_state="investigating" if action == "INCIDENT_STATUS_CHANGED" else None,
        new_state="resolved" if action == "INCIDENT_STATUS_CHANGED" else None,
        metadata={"subject_id": "subject_001"},
    )


def test_every_frozen_action_has_a_valid_audit_boundary() -> None:
    assert {write.action for write in map(_audit_write, AUDIT_ACTION_CODES)} == set(
        AUDIT_ACTION_CODES
    )


@pytest.mark.parametrize("key", ["raw_payload", "password", "token", "traceback"])
def test_audit_boundary_rejects_raw_or_sensitive_metadata(key: str) -> None:
    with pytest.raises(ValidationError, match="forbidden raw or sensitive"):
        AuditWrite(
            action="DEMO_RESET",
            actor_type="system",
            object_type="system",
            object_id="demo",
            request_id="req_reset",
            metadata={key: "must-not-persist"},
        )


def test_incident_audit_query_includes_event_owned_entries() -> None:
    engine, factory = _session_factory()
    with factory() as session:
        AuditRepository(session).append(
            audit_id="aud_event_excluded",
            actor_type="system",
            actor_id="incident_manager",
            action="EVENT_EXCLUDED",
            object_type="event",
            object_id="evt_auth",
            payload={
                "request_id": "req_auth",
                "incident_id": "inc_001",
                "reason_codes": ["EXPLICIT_DIFFERENT_TRACE"],
            },
            timestamp=datetime.now(timezone.utc),
        )
        rows = AuditRepository(session).list_for_incident("inc_001")
        assert [row.id for row in rows] == ["aud_event_excluded"]
    engine.dispose()


def test_ingestion_quarantine_and_collapse_emit_sanitized_audit_outcomes() -> None:
    engine, factory = _session_factory()
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
        session.flush()
        pipeline = IngestionPipeline()
        invalid = json.loads(
            (ADAPTER_FIXTURES / "invalid_alertmanager_alert.json").read_text()
        )
        invalid["authorization"] = "secret-value"
        quarantined = pipeline.ingest(
            source="simulator.alertmanager",
            raw=invalid,
            request_id="req_invalid",
            session=session,
        )
        assert quarantined.status == "quarantined"
        stored = session.get(models.QuarantinedEvent, quarantined.quarantine_id)
        assert stored.raw_payload["authorization"] == "[REDACTED]"

        first_raw = json.loads(
            (ADAPTER_FIXTURES / "valid_alertmanager_alert.json").read_text()
        )
        first = pipeline.ingest(
            source="simulator.alertmanager",
            raw=first_raw,
            request_id="req_first",
            session=session,
        )
        duplicate_raw = dict(first_raw)
        duplicate_raw["fingerprint"] = "alert-gateway-forwarded-duplicate"
        collapsed = pipeline.ingest(
            source="simulator.alertmanager",
            raw=duplicate_raw,
            request_id="req_duplicate",
            session=session,
        )
        assert first.status == "accepted"
        assert collapsed.status == "collapsed"
        assert collapsed.representative_event_id == first.event_id
        actions = {
            row.action for row in AuditRepository(session).list_recent(limit=10)
        }
        assert {"EVENT_QUARANTINED", "EVENT_COLLAPSED"} <= actions
    engine.dispose()
