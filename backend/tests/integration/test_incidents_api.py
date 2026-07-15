from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import incidents as incidents_api
from app.api.incidents import get_session
from app.contracts import InvestigationResponse
from app.db import models
from app.db.repositories import AuditRepository
from app.main import app


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "backend" / "tests" / "fixtures"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _golden_evidence_id(*, missing: bool) -> str:
    golden = _load(FIXTURES / "golden_investigation_response.json")
    top_hypothesis = min(golden["hypotheses"], key=lambda item: item["rank"])
    return next(
        item["evidence_id"]
        for item in golden["evidence_by_hypothesis"][top_hypothesis["hypothesis_id"]]
        if (item["kind"] == "missing") is missing
    )


def _seed(session) -> None:
    golden = _load(FIXTURES / "golden_investigation_response.json")
    topology = _load(ROOT / "backend" / "app" / "fixtures" / "topology.json")
    for node in topology["nodes"]:
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
    for index, edge in enumerate(topology["edges"], start=1):
        session.add(
            models.TopologyEdge(
                id=f"edge_test_{index}",
                source_entity_id=edge["source"],
                target_entity_id=edge["target"],
                relation_type=edge["relation_type"],
                relationship=edge["relationship"],
                active_from=None,
                active_to=None,
            )
        )
    for timeline_item in golden["timeline"]:
        event = timeline_item["event"]
        session.add(
            models.Event(
                id=event["event_id"],
                timestamp=_dt(event["timestamp"]),
                ingested_at=_dt(event["ingested_at"]),
                entity_id=event["entity_id"],
                modality=event["modality"],
                event_type=event["event_type"],
                severity=event["severity"],
                signal_name=event["signal_name"],
                signal_value=event["signal_value"],
                unit=event["unit"],
                trace_or_session_id=event["trace_or_session_id"],
                source=event["source"],
                source_record_id=event["source_record_id"],
                schema_version=event["schema_version"],
                quality_flags=event["quality_flags"],
                raw_payload=event["raw_payload"],
                status="accepted",
            )
        )
    session.flush()

    incident = golden["incident"]
    session.add(
        models.Incident(
            id=incident["incident_id"],
            title=incident["title"],
            status=incident["status"],
            severity=incident["severity"],
            started_at=_dt(incident["started_at"]),
            last_event_at=_dt(incident["last_event_at"]),
            primary_entity_id=incident["primary_entity_id"],
            affected_entity_ids=incident["affected_entity_ids"],
            anomaly_count=incident["anomaly_count"],
            current_analysis_run_id=None,
            top_hypothesis_id=None,
            confirmed_hypothesis_id=None,
        )
    )
    # A second incident exercises tuple-cursor pagination without needing a run.
    session.add(
        models.Incident(
            id="inc_000",
            title="Older baseline incident",
            status="open",
            severity=0.5,
            started_at=_dt(incident["started_at"]) - timedelta(minutes=1),
            last_event_at=_dt(incident["started_at"]) - timedelta(seconds=30),
            primary_entity_id="api-gateway-01",
            affected_entity_ids=["api-gateway-01"],
            anomaly_count=1,
            current_analysis_run_id=None,
            top_hypothesis_id=None,
            confirmed_hypothesis_id=None,
        )
    )
    session.flush()

    run = golden["analysis_run"]
    session.add(
        models.AnalysisRun(
            id=run["analysis_run_id"],
            incident_id=run["incident_id"],
            revision=run["revision"],
            status=run["status"],
            trigger_event_id=run["trigger_event_id"],
            input_fingerprint=run["input_fingerprint"],
            algorithm_version=run["algorithm_version"],
            created_at=_dt(run["created_at"]),
            completed_at=_dt(run["completed_at"]),
            failure_reason=None,
            topology_snapshot=golden["topology"],
        )
    )
    session.add(
        models.AnalysisRun(
            id="run_006",
            incident_id=run["incident_id"],
            revision=6,
            status="superseded",
            trigger_event_id=run["trigger_event_id"],
            input_fingerprint="sha256:" + "6" * 64,
            algorithm_version=run["algorithm_version"],
            created_at=_dt(run["created_at"]) - timedelta(minutes=1),
            completed_at=_dt(run["created_at"]) - timedelta(seconds=30),
            failure_reason=None,
        )
    )
    session.flush()

    for hypothesis in golden["hypotheses"]:
        session.add(
            models.Hypothesis(
                id=hypothesis["hypothesis_id"],
                analysis_run_id=hypothesis["analysis_run_id"],
                incident_id=hypothesis["incident_id"],
                type=hypothesis["hypothesis_type"],
                candidate_entity_id=hypothesis["candidate_entity_id"],
                rank=hypothesis["rank"],
                evidence_score=hypothesis["evidence_score"],
                coverage=hypothesis["evidence_coverage"],
                factor_scores=hypothesis["factor_scores"],
                summary=hypothesis["summary"],
            )
        )
    session.add(
        models.Hypothesis(
            id="hyp_old",
            analysis_run_id="run_006",
            incident_id=incident["incident_id"],
            type="upstream_service_failure",
            candidate_entity_id="auth-api-01",
            rank=1,
            evidence_score=99.9,
            coverage={"available": 1, "expected": 1},
            factor_scores={
                "symptom_compatibility": 1.0,
                "topology_relevance": 1.0,
                "direct_logs_alerts": 1.0,
                "propagation_consistency": 1.0,
                "metric_anomaly": 1.0,
                "change_causal_fit": 1.0,
                "temporal_proximity": 1.0,
                "historical_similarity": 1.0,
            },
            summary="Superseded row that must never enter the current snapshot.",
        )
    )
    session.flush()

    current_incident = session.get(models.Incident, incident["incident_id"])
    current_incident.current_analysis_run_id = run["analysis_run_id"]
    current_incident.top_hypothesis_id = incident["top_hypothesis_id"]
    session.flush()

    for items in golden["evidence_by_hypothesis"].values():
        for evidence in items:
            session.add(
                models.Evidence(
                    id=evidence["evidence_id"],
                    analysis_run_id=evidence["analysis_run_id"],
                    incident_id=evidence["incident_id"],
                    hypothesis_id=evidence["hypothesis_id"],
                    kind=evidence["kind"],
                    source_event_id=evidence["source_event_id"],
                    statement=evidence["statement"],
                    relevance=evidence["relevance"],
                    reason_code=evidence["reason_code"],
                    created_at=_dt(evidence["created_at"]),
                )
            )
    for items in golden["recommendations_by_hypothesis"].values():
        for catalogue_order, recommendation in enumerate(items):
            session.add(
                models.PlaybookRecommendation(
                    id=recommendation["recommendation_id"],
                    analysis_run_id=recommendation["analysis_run_id"],
                    incident_id=recommendation["incident_id"],
                    hypothesis_id=recommendation["hypothesis_id"],
                    step_id=recommendation["step_id"],
                    state="proposed",
                    rationale=recommendation["rationale"],
                    presentation={
                        "title": recommendation["title"],
                        "step_type": recommendation["step_type"],
                        "risk_level": recommendation["risk_level"],
                        "requires_human_approval": recommendation[
                            "requires_human_approval"
                        ],
                        "instructions": recommendation["instructions"],
                        "catalogue_order": catalogue_order,
                    },
                )
            )
    session.add(
        models.Explanation(
            id="exp_007",
            analysis_run_id=run["analysis_run_id"],
            incident_id=run["incident_id"],
            generator="template",
            validated=True,
            payload=golden["explanation"],
            created_at=_dt(run["completed_at"]),
        )
    )
    for timeline_item in golden["timeline"]:
        event_id = timeline_item["event"]["event_id"]
        session.add(
            models.IncidentEventEvaluation(
                incident_id=incident["incident_id"],
                event_id=event_id,
                decision=timeline_item["attachment_decision"],
                attachment_score=timeline_item["attachment_score"],
                attachment_reasons=timeline_item["attachment_reasons"],
            )
        )
        if timeline_item["attachment_decision"] == "attached":
            session.add(
                models.IncidentEvent(
                    incident_id=incident["incident_id"],
                    event_id=event_id,
                    attachment_score=timeline_item["attachment_score"],
                    attachment_reasons=timeline_item["attachment_reasons"],
                )
            )
    session.add(
        models.AuditLog(
            id="aud_seed",
            timestamp=_dt(run["completed_at"]),
            actor_type="system",
            actor_id="orchestrator",
            action="ANALYSIS_PUBLISHED",
            object_type="incident",
            object_id=incident["incident_id"],
            payload={
                "request_id": "req_seed",
                "analysis_run_id": run["analysis_run_id"],
                "revision": run["revision"],
            },
        )
    )
    excluded_auth = next(
        item
        for item in golden["timeline"]
        if item["attachment_decision"] == "excluded"
    )
    session.add(
        models.AuditLog(
            id="aud_auth_excluded",
            timestamp=_dt(excluded_auth["event"]["timestamp"]),
            actor_type="system",
            actor_id="incident_manager",
            action="EVENT_EXCLUDED",
            object_type="event",
            object_id=excluded_auth["event"]["event_id"],
            payload={
                "request_id": "req_auth_excluded",
                "incident_id": incident["incident_id"],
                "event_id": excluded_auth["event"]["event_id"],
                "reason_codes": excluded_auth["attachment_reasons"],
            },
        )
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
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    with testing_session() as session:
        _seed(session)

    def override_session():
        session = testing_session()
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


def test_investigation_is_one_current_run_snapshot(client: TestClient) -> None:
    response = client.get("/api/v1/incidents/inc_001/investigation")

    assert response.status_code == 200
    payload = response.json()
    snapshot = InvestigationResponse.model_validate(payload)
    snapshot.assert_consistent_run()
    assert payload["analysis_run_id"] == "run_007"
    assert {item["hypothesis_id"] for item in payload["hypotheses"]} == {
        "hyp_001",
        "hyp_002",
        "hyp_003",
    }
    assert "hyp_old" not in json.dumps(payload)
    auth = next(
        item
        for item in payload["timeline"]
        if item["event"]["source_record_id"] == "log-auth-certificate-0001"
    )
    assert auth["attachment_decision"] == "excluded"
    assert auth["hypothesis_relevance"] == {}
    assert any(item["hypothesis_relevance"] for item in payload["timeline"] if item is not auth)


def test_published_topology_and_recommendations_do_not_reload_live_catalogues(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = client.get("/api/v1/incidents/inc_001/investigation")
    assert first.status_code == 200

    def fail_live_catalogue_read(*_args, **_kwargs):
        raise AssertionError("a published investigation must not reload live fixtures")

    import app.playbooks.engine as playbook_engine
    import app.topology.graph as topology_graph

    monkeypatch.setattr(playbook_engine, "get_step", fail_live_catalogue_read)
    monkeypatch.setattr(topology_graph, "get_topology_graph", fail_live_catalogue_read)

    second = client.get("/api/v1/incidents/inc_001/investigation")
    assert second.status_code == 200
    assert second.json()["topology"] == first.json()["topology"]
    assert (
        second.json()["recommendations_by_hypothesis"]
        == first.json()["recommendations_by_hypothesis"]
    )


def test_investigation_keeps_captured_run_when_pointer_changes_mid_assembly(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_timeline = incidents_api._timeline_items_for_run
    original_explanation = incidents_api._explanation_for_run
    captured_run_ids: list[str] = []

    def change_pointer_then_read_captured_timeline(
        session,
        incident_id: str,
        analysis_run_id: str,
    ):
        captured_run_ids.append(analysis_run_id)
        incident = session.get(models.Incident, incident_id)
        incident.current_analysis_run_id = "run_006"
        incident.top_hypothesis_id = "hyp_old"
        session.flush()
        return original_timeline(session, incident_id, analysis_run_id)

    def read_captured_explanation(
        session,
        incident_id: str,
        analysis_run_id: str,
        hypothesis_id: str,
    ):
        captured_run_ids.append(analysis_run_id)
        return original_explanation(
            session,
            incident_id,
            analysis_run_id,
            hypothesis_id,
        )

    monkeypatch.setattr(
        incidents_api,
        "_timeline_items_for_run",
        change_pointer_then_read_captured_timeline,
    )
    monkeypatch.setattr(
        incidents_api,
        "_explanation_for_run",
        read_captured_explanation,
    )

    response = client.get("/api/v1/incidents/inc_001/investigation")

    assert response.status_code == 200
    snapshot = InvestigationResponse.model_validate(response.json())
    snapshot.assert_consistent_run()
    assert captured_run_ids == ["run_007", "run_007"]
    assert snapshot.analysis_run_id == "run_007"
    assert snapshot.incident.current_analysis_run_id == "run_007"
    assert {item.analysis_run_id for item in snapshot.hypotheses} == {"run_007"}
    node_states = {node.id: node.state for node in snapshot.topology.nodes}
    assert node_states["api-gateway-01"] == "suspected_root"
    assert node_states["auth-api-01"] != "suspected_root"
    assert "hyp_old" not in response.text


def test_incident_reads_and_cursor_pagination(client: TestClient) -> None:
    summary = client.get("/api/v1/incidents/inc_001")
    assert summary.status_code == 200
    assert summary.json()["current_analysis_run_id"] == "run_007"

    first = client.get("/api/v1/incidents", params={"limit": 1})
    assert first.status_code == 200
    assert [item["incident_id"] for item in first.json()["items"]] == ["inc_001"]
    cursor = first.json()["next_cursor"]
    assert cursor

    second = client.get("/api/v1/incidents", params={"limit": 1, "cursor": cursor})
    assert second.status_code == 200
    assert [item["incident_id"] for item in second.json()["items"]] == ["inc_000"]

    changed_filter = client.get(
        "/api/v1/incidents",
        params={"limit": 1, "cursor": cursor, "status": "investigating"},
    )
    assert changed_filter.status_code == 400
    assert changed_filter.json()["error"]["code"] == "INVALID_CURSOR"


def test_current_run_read_endpoints_never_return_superseded_rows(client: TestClient) -> None:
    hypotheses = client.get("/api/v1/incidents/inc_001/hypotheses")
    evidence = client.get("/api/v1/incidents/inc_001/evidence")
    recommendations = client.get("/api/v1/incidents/inc_001/recommendations")
    explanation = client.get("/api/v1/incidents/inc_001/explanation")
    timeline = client.get("/api/v1/incidents/inc_001/timeline")

    assert all(response.status_code == 200 for response in (
        hypotheses, evidence, recommendations, explanation, timeline
    ))
    assert {item["analysis_run_id"] for item in hypotheses.json()} == {"run_007"}
    assert {
        item["analysis_run_id"]
        for items in evidence.json().values()
        for item in items
    } == {"run_007"}
    assert {
        item["analysis_run_id"]
        for items in recommendations.json().values()
        for item in items
    } == {"run_007"}
    assert explanation.json()["analysis_run_id"] == "run_007"
    assert explanation.json()["summary"] == _load(
        FIXTURES / "golden_investigation_response.json"
    )["explanation"]["summary"]

    timeline_items = timeline.json()["items"]
    excluded = next(
        item for item in timeline_items if item["attachment_decision"] == "excluded"
    )
    assert excluded["hypothesis_relevance"] == {}
    assert any(
        item["hypothesis_relevance"]
        for item in timeline_items
        if item["attachment_decision"] == "attached"
    )


def test_review_is_idempotent_audited_and_closes_on_confirmation(
    client: TestClient,
) -> None:
    request_evidence = {
        "analysis_run_id": "run_007",
        "hypothesis_id": "hyp_001",
        "decision": "evidence_requested",
        "client_action_id": "action-request-waf",
        "requested_evidence_id": _golden_evidence_id(missing=True),
        "reviewer": "operator-1",
        "comment": "Collect WAF logs",
    }
    first = client.post("/api/v1/incidents/inc_001/review", json=request_evidence)
    retry = client.post("/api/v1/incidents/inc_001/review", json=request_evidence)
    assert first.status_code == retry.status_code == 200
    assert first.json()["review"]["review_id"] == retry.json()["review"]["review_id"]
    assert first.json()["request_id"] == retry.json()["request_id"]
    assert first.json()["generated_at"] == retry.json()["generated_at"]

    confirm = client.post(
        "/api/v1/incidents/inc_001/review",
        json={
            "analysis_run_id": "run_007",
            "hypothesis_id": "hyp_001",
            "decision": "confirmed",
            "client_action_id": "action-confirm",
            "requested_evidence_id": None,
            "reviewer": "operator-1",
            "comment": "Confirmed from config diff",
        },
    )
    assert confirm.status_code == 200
    assert client.get("/api/v1/incidents/inc_001").json()["status"] == "resolved"

    audit = client.get("/api/v1/incidents/inc_001/audit")
    assert audit.status_code == 200
    assert {item["action"] for item in audit.json()["items"]} >= {
        "EVENT_EXCLUDED",
        "REVIEW_EVIDENCE_REQUESTED",
        "REVIEW_CONFIRMED",
        "INCIDENT_STATUS_CHANGED",
    }
    review_actions = [
        item for item in audit.json()["items"] if item["action"] == "REVIEW_EVIDENCE_REQUESTED"
    ]
    assert len(review_actions) == 1

    closed = client.post(
        "/api/v1/incidents/inc_001/review",
        json={
            **request_evidence,
            "client_action_id": "action-after-close",
        },
    )
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "INCIDENT_CLOSED"


def test_stale_and_non_missing_evidence_reviews_are_rejected(client: TestClient) -> None:
    stale = client.post(
        "/api/v1/incidents/inc_001/review",
        json={
            "analysis_run_id": "run_006",
            "hypothesis_id": "hyp_old",
            "decision": "rejected",
            "client_action_id": "stale-action",
            "requested_evidence_id": None,
            "reviewer": "operator-1",
            "comment": "stale",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_ANALYSIS"
    assert {
        item["reason_code"] for item in stale.json()["error"]["details"]
    } == {"run_007"}

    non_missing = client.post(
        "/api/v1/incidents/inc_001/review",
        json={
            "analysis_run_id": "run_007",
            "hypothesis_id": "hyp_001",
            "decision": "evidence_requested",
            "client_action_id": "invalid-evidence-action",
            "requested_evidence_id": _golden_evidence_id(missing=False),
            "reviewer": "operator-1",
            "comment": "invalid",
        },
    )
    assert non_missing.status_code == 422
    assert non_missing.json()["error"]["code"] == "VALIDATION_ERROR"


def test_review_audit_failure_rolls_back_review_and_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_append = AuditRepository.append

    def fail_review_audit(self, **kwargs):
        if str(kwargs.get("action", "")).startswith("REVIEW_"):
            raise RuntimeError("forced audit failure")
        return original_append(self, **kwargs)

    monkeypatch.setattr(AuditRepository, "append", fail_review_audit)
    with pytest.raises(RuntimeError, match="forced audit failure"):
        client.post(
            "/api/v1/incidents/inc_001/review",
            json={
                "analysis_run_id": "run_007",
                "hypothesis_id": "hyp_001",
                "decision": "confirmed",
                "client_action_id": "action-must-rollback",
                "requested_evidence_id": None,
                "reviewer": "operator-1",
                "comment": "must roll back",
            },
        )

    investigation = client.get("/api/v1/incidents/inc_001/investigation").json()
    assert investigation["incident"]["status"] == "investigating"
    assert all(
        item["client_action_id"] != "action-must-rollback"
        for item in investigation["reviews"]
    )


def test_recompute_is_safe_when_p4_analysis_engine_is_not_registered(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(incidents_api.orchestrator, "_analysis_engine", None)
    response = client.post("/api/v1/incidents/inc_001/recompute")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_READY"
