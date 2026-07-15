from __future__ import annotations

import json
from pathlib import Path

from app.contracts import (
    AnalysisRun,
    AnomalyRecord,
    AuditRecord,
    CanonicalEvent,
    ErrorEnvelope,
    EvidenceItem,
    Hypothesis,
    IncidentSummary,
    InvestigationResponse,
    ReviewMutationResponse,
    ReviewRecord,
    ReviewRequest,
)
from app.main import app


ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "backend" / "app" / "contracts" / "examples"
FIXTURES = ROOT / "backend" / "tests" / "fixtures"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_examples_validate() -> None:
    models = {
        "canonical_event.json": CanonicalEvent,
        "anomaly.json": AnomalyRecord,
        "incident.json": IncidentSummary,
        "hypothesis.json": Hypothesis,
        "evidence.json": EvidenceItem,
        "review.json": ReviewRecord,
        "review-request.json": ReviewRequest,
        "review-mutation-response.json": ReviewMutationResponse,
        "analysis_run.json": AnalysisRun,
        "error.json": ErrorEnvelope,
    }
    for filename, model in models.items():
        model.model_validate(load(EXAMPLES / filename))


def test_golden_events_and_anomalies_validate() -> None:
    events = [
        CanonicalEvent.model_validate_json(line)
        for line in (FIXTURES / "golden_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(events) >= 20
    anomaly_bundle = load(FIXTURES / "golden_anomalies.json")
    anomalies = [AnomalyRecord.model_validate(item) for item in anomaly_bundle["anomalies"]]
    markers = [AnomalyRecord.model_validate(item) for item in anomaly_bundle["context_markers"]]
    assert len(anomalies) == anomaly_bundle["actionable_anomaly_count"] == 9
    assert len(markers) == 1
    assert markers[0].context_only is True
    assert markers[0].can_open_incident is False


def test_analysis_and_incident_handoffs_validate() -> None:
    analysis = load(FIXTURES / "golden_expected_analysis.json")
    hypotheses = [Hypothesis.model_validate(item) for item in analysis["hypotheses"]]
    assert [item.evidence_score for item in hypotheses] == [92.1, 65.6, 41.5]
    bundle = load(FIXTURES / "golden_incident_bundle.json")
    IncidentSummary.model_validate(bundle["incident"])
    attached_ids = {item["event_id"] for item in bundle["attached_events"]}
    excluded_ids = {item["event_id"] for item in bundle["excluded_events"]}
    assert attached_ids.isdisjoint(excluded_ids)


def test_investigation_response_is_one_consistent_snapshot() -> None:
    response = InvestigationResponse.model_validate(load(FIXTURES / "golden_investigation_response.json"))
    response.assert_consistent_run()
    attached_evidence_ids = {
        item.event.event_id
        for item in response.timeline
        if item.attachment_decision == "attached"
    }
    for items in response.evidence_by_hypothesis.values():
        for evidence in items:
            if evidence.source_event_id is not None:
                assert evidence.source_event_id in attached_evidence_ids


def test_review_and_audit_examples_validate() -> None:
    reviews = load(FIXTURES / "golden_review_examples.json")["records"]
    audits = load(FIXTURES / "golden_audit_examples.json")["records"]
    assert all(ReviewRecord.model_validate(item) for item in reviews)
    assert all(AuditRecord.model_validate(item) for item in audits)


def test_phase3_review_seed_resolves_against_golden_snapshot() -> None:
    seed = load(FIXTURES / "phase3_review_seed.json")
    investigation = InvestigationResponse.model_validate(
        load(FIXTURES / "golden_investigation_response.json")
    )
    assert seed["incident_id"] == investigation.incident.incident_id
    assert seed["current_analysis_run_id"] == investigation.analysis_run_id
    assert set(seed["current_hypothesis_ids"]) == {
        item.hypothesis_id for item in investigation.hypotheses
    }
    evidence = [
        item
        for items in investigation.evidence_by_hypothesis.values()
        for item in items
    ]
    assert any(
        item.evidence_id == seed["missing_evidence_id"] and item.kind.value == "missing"
        for item in evidence
    )
    assert any(
        item.evidence_id == seed["non_missing_evidence_id"]
        and item.kind.value != "missing"
        for item in evidence
    )
    assert any(
        item.event.event_id == seed["excluded_event_id"]
        and item.attachment_decision == "excluded"
        for item in investigation.timeline
    )
    assert seed["initial_review_ids"] == []


def test_openapi_contains_every_frozen_endpoint() -> None:
    document = app.openapi()
    paths = set(document["paths"])
    required = {
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/events",
        "/api/v1/events/batch",
        "/api/v1/events/{event_id}",
        "/api/v1/quarantine",
        "/api/v1/anomalies",
        "/api/v1/simulator/start",
        "/api/v1/simulator/stop",
        "/api/v1/simulator/reset",
        "/api/v1/simulator/scenarios",
        "/api/v1/simulator/scenarios/{scenario_id}/trigger",
        "/api/v1/simulator/status",
        "/api/v1/incidents",
        "/api/v1/incidents/{incident_id}",
        "/api/v1/incidents/{incident_id}/investigation",
        "/api/v1/incidents/{incident_id}/timeline",
        "/api/v1/incidents/{incident_id}/hypotheses",
        "/api/v1/incidents/{incident_id}/evidence",
        "/api/v1/incidents/{incident_id}/recommendations",
        "/api/v1/incidents/{incident_id}/explanation",
        "/api/v1/incidents/{incident_id}/recompute",
        "/api/v1/incidents/{incident_id}/review",
        "/api/v1/incidents/{incident_id}/audit",
        "/api/v1/topology",
        "/api/v1/topology/path",
        "/api/v1/topology/blast-radius/{entity_id}",
    }
    assert required <= paths

    event_responses = document["paths"]["/api/v1/events"]["post"]["responses"]
    assert {"200", "201", "202", "422"} <= set(event_responses)
    assert "503" in document["paths"]["/api/v1/ready"]["get"]["responses"]

    typed_operations = (
        ("/api/v1/ready", "get", "200"),
        ("/api/v1/quarantine", "get", "200"),
        ("/api/v1/incidents/{incident_id}/timeline", "get", "200"),
        ("/api/v1/incidents/{incident_id}/recompute", "post", "200"),
        ("/api/v1/topology/path", "get", "200"),
        ("/api/v1/topology/blast-radius/{entity_id}", "get", "200"),
    )
    for path, method, response_status in typed_operations:
        schema = document["paths"][path][method]["responses"][response_status]["content"][
            "application/json"
        ]["schema"]
        assert schema and ("$ref" in schema or schema.get("type") != "object" or schema.get("properties"))

    error_schema = document["paths"]["/api/v1/incidents/{incident_id}"]["get"][
        "responses"
    ]["404"]["content"]["application/json"]["schema"]
    assert error_schema["$ref"].endswith("/ErrorEnvelope")
