from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_session
from app.audit.contracts import AuditWrite
from app.audit.service import audit_service
from app.db import models
from app.main import app


NOW = datetime(2026, 7, 14, 9, 32, tzinfo=timezone.utc)
INCIDENT_ID = "inc_phase3"
RUN_ID = "run_phase3_current"
OLD_RUN_ID = "run_phase3_old"
HYPOTHESIS_IDS = ("hyp_phase3_1", "hyp_phase3_2", "hyp_phase3_3")
MISSING_EVIDENCE_ID = "ev_phase3_missing"
OBSERVED_EVIDENCE_ID = "ev_phase3_observed"
AUTH_EVENT_ID = "evt_phase3_auth_warning"


def _seed(session) -> None:
    session.add_all(
        [
            models.Entity(
                id="api-gateway-01",
                name="API Gateway",
                entity_type="gateway",
                service="api-gateway",
                criticality="critical",
                metadata_json={},
            ),
            models.Entity(
                id="auth-api-01",
                name="Auth API",
                entity_type="service",
                service="auth-api",
                criticality="high",
                metadata_json={},
            ),
        ]
    )
    session.add_all(
        [
            models.Event(
                id="evt_phase3_gateway",
                timestamp=NOW - timedelta(seconds=90),
                ingested_at=NOW - timedelta(seconds=89),
                entity_id="api-gateway-01",
                modality="metric",
                event_type="FORWARDED_REQUEST_RATE",
                severity=0.0,
                signal_name="forwarded_requests_per_second",
                signal_value=7800.0,
                unit="requests/s",
                trace_or_session_id="scenario_gateway_rate_limit_001",
                source="simulator.prometheus",
                source_record_id="phase3-gateway",
                schema_version="1.0",
                quality_flags=["SIMULATED"],
                raw_payload={"sample_id": "phase3-gateway"},
                status="accepted",
            ),
            models.Event(
                id=AUTH_EVENT_ID,
                timestamp=NOW,
                ingested_at=NOW + timedelta(milliseconds=120),
                entity_id="auth-api-01",
                modality="log",
                event_type="CERTIFICATE_EXPIRY_WARNING",
                severity=0.35,
                signal_name=None,
                signal_value=None,
                unit=None,
                trace_or_session_id="maintenance_auth_001",
                source="simulator.syslog",
                source_record_id="phase3-auth-warning",
                schema_version="1.0",
                quality_flags=["SIMULATED"],
                raw_payload={"code": "CERTIFICATE_EXPIRY_WARNING"},
                status="accepted",
            ),
        ]
    )
    session.flush()
    incident = models.Incident(
        id=INCIDENT_ID,
        title="Phase 3 review incident",
        status="investigating",
        severity=0.95,
        started_at=NOW - timedelta(minutes=2),
        last_event_at=NOW - timedelta(seconds=20),
        primary_entity_id="api-gateway-01",
        affected_entity_ids=["api-gateway-01"],
        anomaly_count=9,
        current_analysis_run_id=None,
        top_hypothesis_id=None,
        confirmed_hypothesis_id=None,
    )
    session.add(incident)
    session.flush()
    session.add_all(
        [
            models.AnalysisRun(
                id=RUN_ID,
                incident_id=INCIDENT_ID,
                revision=7,
                status="current",
                trigger_event_id="evt_phase3_gateway",
                input_fingerprint="sha256:" + "7" * 64,
                algorithm_version="rca-rules-1.1",
                created_at=NOW - timedelta(seconds=20),
                completed_at=NOW - timedelta(seconds=19),
                failure_reason=None,
            ),
            models.AnalysisRun(
                id=OLD_RUN_ID,
                incident_id=INCIDENT_ID,
                revision=6,
                status="superseded",
                trigger_event_id="evt_phase3_gateway",
                input_fingerprint="sha256:" + "6" * 64,
                algorithm_version="rca-rules-1.1",
                created_at=NOW - timedelta(minutes=1),
                completed_at=NOW - timedelta(seconds=50),
                failure_reason=None,
            ),
        ]
    )
    session.flush()
    for rank, hypothesis_id in enumerate(HYPOTHESIS_IDS, start=1):
        session.add(
            models.Hypothesis(
                id=hypothesis_id,
                analysis_run_id=RUN_ID,
                incident_id=INCIDENT_ID,
                type=(
                    "configuration_regression"
                    if rank == 1
                    else f"phase3_alternative_{rank}"
                ),
                candidate_entity_id="api-gateway-01",
                rank=rank,
                evidence_score=100.0 - rank,
                coverage={"available": 1, "expected": 2},
                factor_scores={},
                summary=f"Phase 3 hypothesis {rank}",
            )
        )
    session.add(
        models.Hypothesis(
            id="hyp_phase3_old",
            analysis_run_id=OLD_RUN_ID,
            incident_id=INCIDENT_ID,
            type="superseded_candidate",
            candidate_entity_id="auth-api-01",
            rank=1,
            evidence_score=99.0,
            coverage={"available": 1, "expected": 1},
            factor_scores={},
            summary="Old hypothesis",
        )
    )
    session.flush()
    incident.current_analysis_run_id = RUN_ID
    incident.top_hypothesis_id = HYPOTHESIS_IDS[0]
    session.add_all(
        [
            models.Evidence(
                id=MISSING_EVIDENCE_ID,
                analysis_run_id=RUN_ID,
                incident_id=INCIDENT_ID,
                hypothesis_id=HYPOTHESIS_IDS[0],
                kind="missing",
                source_event_id=None,
                statement="Obtain WAF decision logs.",
                relevance=0.5,
                reason_code="MISSING_WAF_DECISION_LOGS",
                created_at=NOW - timedelta(seconds=18),
            ),
            models.Evidence(
                id=OBSERVED_EVIDENCE_ID,
                analysis_run_id=RUN_ID,
                incident_id=INCIDENT_ID,
                hypothesis_id=HYPOTHESIS_IDS[0],
                kind="observed",
                source_event_id="evt_phase3_gateway",
                statement="Gateway forwarding reached 7,800 requests/s.",
                relevance=0.95,
                reason_code="METRIC_THRESHOLD_EXCEEDED",
                created_at=NOW - timedelta(seconds=18),
            ),
        ]
    )
    audit_service.append(
        AuditWrite(
            action="EVENT_EXCLUDED",
            actor_type="system",
            actor_id="incident_manager",
            object_type="event",
            object_id=AUTH_EVENT_ID,
            incident_id=INCIDENT_ID,
            request_id="pipeline:phase3-auth-warning",
            reason_codes=[
                "INCOMPATIBLE_MAINTENANCE_SYMPTOM",
                "EXPLICIT_DIFFERENT_TRACE",
            ],
            metadata={
                "event_id": AUTH_EVENT_ID,
                "decision": "excluded",
                "attachment_score": -0.15,
            },
        ),
        session,
        timestamp=NOW,
        audit_id="aud_phase3_auth_excluded",
    )
    session.commit()


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        _seed(session)

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

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def _review(
    client: TestClient,
    *,
    decision: str,
    hypothesis_id: str = HYPOTHESIS_IDS[0],
    client_action_id: str,
    requested_evidence_id: str | None = None,
    analysis_run_id: str = RUN_ID,
):
    return client.post(
        f"/api/v1/incidents/{INCIDENT_ID}/review",
        json={
            "analysis_run_id": analysis_run_id,
            "hypothesis_id": hypothesis_id,
            "decision": decision,
            "client_action_id": client_action_id,
            "requested_evidence_id": requested_evidence_id,
            "reviewer": "phase3-operator",
            "comment": f"Phase 3 {decision}",
        },
    )


def test_confirm_resolves_incident_and_writes_review_audit(client: TestClient) -> None:
    response = _review(
        client, decision="confirmed", client_action_id="phase3-confirm"
    )
    assert response.status_code == 200
    summary = client.get(f"/api/v1/incidents/{INCIDENT_ID}").json()
    assert summary["status"] == "resolved"
    assert summary["confirmed_hypothesis_id"] == HYPOTHESIS_IDS[0]
    audit = client.get(f"/api/v1/incidents/{INCIDENT_ID}/audit").json()
    confirmed = next(row for row in audit if row["action"] == "REVIEW_CONFIRMED")
    assert confirmed["request_id"] == response.json()["request_id"]
    assert confirmed["payload"]["analysis_revision"] == 7
    assert any(row["action"] == "INCIDENT_STATUS_CHANGED" for row in audit)


def test_rejecting_every_current_hypothesis_rejects_incident(
    client: TestClient,
) -> None:
    for index, hypothesis_id in enumerate(HYPOTHESIS_IDS, start=1):
        response = _review(
            client,
            decision="rejected",
            hypothesis_id=hypothesis_id,
            client_action_id=f"phase3-reject-{index}",
        )
        assert response.status_code == 200
        if index < len(HYPOTHESIS_IDS):
            interim = client.get(f"/api/v1/incidents/{INCIDENT_ID}").json()
            assert interim["status"] == "investigating"
    summary = client.get(f"/api/v1/incidents/{INCIDENT_ID}").json()
    assert summary["status"] == "rejected"
    audit = client.get(f"/api/v1/incidents/{INCIDENT_ID}/audit").json()
    assert sum(row["action"] == "REVIEW_REJECTED" for row in audit) == 3
    assert any(
        row["action"] == "INCIDENT_STATUS_CHANGED"
        and row["payload"]["new_state"] == "rejected"
        for row in audit
    )


def test_duplicate_client_action_returns_existing_without_duplicate_audit(
    client: TestClient,
) -> None:
    first = _review(
        client,
        decision="evidence_requested",
        client_action_id="phase3-request-evidence",
        requested_evidence_id=MISSING_EVIDENCE_ID,
    )
    retry = _review(
        client,
        decision="evidence_requested",
        client_action_id="phase3-request-evidence",
        requested_evidence_id=MISSING_EVIDENCE_ID,
    )
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    audit = client.get(f"/api/v1/incidents/{INCIDENT_ID}/audit").json()
    assert (
        sum(row["action"] == "REVIEW_EVIDENCE_REQUESTED" for row in audit) == 1
    )


def test_stale_run_returns_current_run_id(client: TestClient) -> None:
    response = _review(
        client,
        decision="rejected",
        client_action_id="phase3-stale",
        analysis_run_id=OLD_RUN_ID,
        hypothesis_id="hyp_phase3_old",
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STALE_ANALYSIS"
    assert response.json()["detail"]["details"] == [
        {"field": "current_analysis_run_id", "reason_code": RUN_ID}
    ]


def test_evidence_request_rejects_non_missing_evidence(client: TestClient) -> None:
    response = _review(
        client,
        decision="evidence_requested",
        client_action_id="phase3-invalid-evidence",
        requested_evidence_id=OBSERVED_EVIDENCE_ID,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_conflicting_terminal_review_and_closed_incident_are_rejected(
    client: TestClient,
) -> None:
    rejected = _review(
        client, decision="rejected", client_action_id="phase3-first-terminal"
    )
    assert rejected.status_code == 200
    conflict = _review(
        client, decision="confirmed", client_action_id="phase3-conflict"
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "REVIEW_CONFLICT"

    confirmed = _review(
        client,
        decision="confirmed",
        hypothesis_id=HYPOTHESIS_IDS[1],
        client_action_id="phase3-close-incident",
    )
    assert confirmed.status_code == 200
    closed = _review(
        client,
        decision="rejected",
        hypothesis_id=HYPOTHESIS_IDS[2],
        client_action_id="phase3-after-close",
    )
    assert closed.status_code == 409
    assert closed.json()["detail"]["code"] == "INCIDENT_CLOSED"


def test_auth_warning_exclusion_is_visible_in_incident_audit(
    client: TestClient,
) -> None:
    audit = client.get(f"/api/v1/incidents/{INCIDENT_ID}/audit")
    assert audit.status_code == 200
    excluded = next(row for row in audit.json() if row["action"] == "EVENT_EXCLUDED")
    assert excluded["object_id"] == AUTH_EVENT_ID
    assert excluded["payload"]["reason_codes"] == [
        "INCOMPATIBLE_MAINTENANCE_SYMPTOM",
        "EXPLICIT_DIFFERENT_TRACE",
    ]
