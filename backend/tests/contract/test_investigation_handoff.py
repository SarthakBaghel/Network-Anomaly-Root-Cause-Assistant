from __future__ import annotations

import json
from pathlib import Path

from app.contracts import InvestigationResponse


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "backend" / "tests" / "fixtures"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_golden_investigation_handoff_has_resolvable_consistent_references() -> None:
    response = InvestigationResponse.model_validate(
        _load(FIXTURES / "golden_investigation_response.json")
    )
    response.assert_consistent_run()
    run_id = response.analysis_run_id

    assert all(item.analysis_run_id == run_id for item in response.hypotheses)
    assert all(
        item.analysis_run_id == run_id
        for items in response.evidence_by_hypothesis.values()
        for item in items
    )
    assert all(
        item.analysis_run_id == run_id
        for items in response.recommendations_by_hypothesis.values()
        for item in items
    )
    assert response.explanation.analysis_run_id == run_id
    assert all(item.analysis_run_id == run_id for item in response.reviews)

    hypothesis_ids = {item.hypothesis_id for item in response.hypotheses}
    assert set(response.evidence_by_hypothesis) == hypothesis_ids
    assert set(response.recommendations_by_hypothesis) == hypothesis_ids
    assert response.incident.top_hypothesis_id in hypothesis_ids
    assert response.explanation.hypothesis_id in hypothesis_ids

    timeline_ids = {item.event.event_id for item in response.timeline}
    attached_ids = {
        item.event.event_id
        for item in response.timeline
        if item.attachment_decision == "attached"
    }
    excluded = [
        item for item in response.timeline if item.attachment_decision == "excluded"
    ]
    assert len(timeline_ids) == len(response.timeline)
    assert len(excluded) == 1
    assert excluded[0].event.source_record_id == "log-auth-certificate-0001"
    assert excluded[0].hypothesis_relevance == {}

    evidence_ids = {
        item.evidence_id
        for items in response.evidence_by_hypothesis.values()
        for item in items
    }
    relevance_by_event: dict[str, dict[str, set[str]]] = {}
    for hypothesis_id, items in response.evidence_by_hypothesis.items():
        for item in items:
            assert item.hypothesis_id == hypothesis_id
            if item.source_event_id is not None:
                assert item.source_event_id in attached_ids
                relevance_by_event.setdefault(item.source_event_id, {}).setdefault(
                    hypothesis_id, set()
                ).add(item.reason_code)
    for item in response.timeline:
        assert item.event.event_id in timeline_ids
        for hypothesis_id, reason_codes in item.hypothesis_relevance.items():
            assert hypothesis_id in hypothesis_ids
            assert set(reason_codes) <= relevance_by_event[item.event.event_id][hypothesis_id]

    for hypothesis_id, items in response.recommendations_by_hypothesis.items():
        assert all(item.hypothesis_id == hypothesis_id for item in items)
    assert all(
        evidence_id in evidence_ids
        for claim in response.explanation.claims
        for evidence_id in claim.evidence_ids
    )


def test_golden_investigation_contains_the_complete_typed_topology() -> None:
    response = InvestigationResponse.model_validate(
        _load(FIXTURES / "golden_investigation_response.json")
    )
    topology = _load(ROOT / "backend" / "app" / "fixtures" / "topology.json")

    assert response.topology.fixture_version == topology["version"]
    assert {node.id for node in response.topology.nodes} == {
        node["id"] for node in topology["nodes"]
    }
    assert {
        (edge.source, edge.target, edge.relation_type.value)
        for edge in response.topology.edges
    } == {
        (edge["source"], edge["target"], edge["relation_type"])
        for edge in topology["edges"]
    }
