from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.contracts import CanonicalEvent, EvidenceKind, Hypothesis
from app.evidence.collector import calculate_evidence_coverage, collect_evidence


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CATALOGUE = Path(__file__).resolve().parents[2] / "app" / "fixtures" / "hypotheses.yaml"


def _golden_inputs() -> tuple[dict[str, Hypothesis], dict[str, dict], list[CanonicalEvent]]:
    expected = json.loads((FIXTURES / "golden_expected_analysis.json").read_text())
    hypotheses = {
        item["hypothesis_type"]: Hypothesis.model_validate(item)
        for item in expected["hypotheses"]
    }
    catalogue_rows = yaml.safe_load(CATALOGUE.read_text())["hypotheses"]
    catalogue = {row["hypothesis_type"]: row for row in catalogue_rows}
    all_events = {
        event.event_id: event
        for event in (
            CanonicalEvent.model_validate_json(line)
            for line in (FIXTURES / "golden_events.jsonl").read_text().splitlines()
        )
    }
    incident_bundle = json.loads((FIXTURES / "golden_incident_bundle.json").read_text())
    incident_events = [
        all_events[row["event_id"]] for row in incident_bundle["attached_events"]
    ]
    return hypotheses, catalogue, incident_events


def test_golden_configuration_evidence_has_all_four_categories() -> None:
    hypotheses, catalogue, events = _golden_inputs()
    hypothesis = hypotheses["configuration_regression"]

    evidence = collect_evidence(hypothesis, events, catalogue[hypothesis.hypothesis_type], [])

    assert sum(item.kind is EvidenceKind.OBSERVED for item in evidence) >= 2
    assert any(item.kind is EvidenceKind.CORRELATED for item in evidence)
    assert any(item.kind is EvidenceKind.CONFLICTING for item in evidence)
    assert any(item.kind is EvidenceKind.MISSING for item in evidence)
    assert calculate_evidence_coverage(catalogue[hypothesis.hypothesis_type], evidence) == (
        hypothesis.evidence_coverage
    )


def test_waf_requirement_produces_exactly_one_catalogue_templated_request() -> None:
    hypotheses, catalogue, events = _golden_inputs()
    hypothesis = hypotheses["configuration_regression"]
    entry = catalogue[hypothesis.hypothesis_type]

    evidence = collect_evidence(hypothesis, events, entry, [])
    waf = [
        item
        for item in evidence
        if item.kind is EvidenceKind.MISSING
        and item.reason_code.endswith("WAF_DECISION_LOGS")
    ]

    assert len(waf) == 1
    assert waf[0].statement == entry["expected_evidence"]["waf_decision_logs"]
    assert waf[0].source_event_id is None


def test_ranker_conflict_reason_codes_match_factor_reductions() -> None:
    hypotheses, catalogue, events = _golden_inputs()
    checks = (
        ("dos_or_traffic_surge", "STABLE_RAW_INGRESS", "symptom_compatibility"),
        ("database_connection_exhaustion", "NORMAL_DB_UTILIZATION", "metric_anomaly"),
    )

    for hypothesis_type, reason_code, factor_name in checks:
        hypothesis = hypotheses[hypothesis_type]
        entry = catalogue[hypothesis_type]
        pattern = next(
            item for item in entry["conflict_patterns"] if item["pattern_id"] == reason_code
        )
        evidence = collect_evidence(hypothesis, events, entry, [])

        assert any(
            item.kind is EvidenceKind.CONFLICTING and item.reason_code == reason_code
            for item in evidence
        )
        assert pattern["operation"] == "cap"
        assert hypothesis.factor_scores[factor_name] == pattern["value"]


def test_missing_source_event_is_null_if_and_only_if_missing() -> None:
    hypotheses, catalogue, events = _golden_inputs()

    for hypothesis_type, hypothesis in hypotheses.items():
        evidence = collect_evidence(hypothesis, events, catalogue[hypothesis_type], [])
        for item in evidence:
            assert (item.source_event_id is None) is (item.kind is EvidenceKind.MISSING)


def test_quarantined_record_does_not_satisfy_expected_evidence() -> None:
    hypotheses, catalogue, events = _golden_inputs()
    hypothesis = hypotheses["configuration_regression"]
    entry = catalogue[hypothesis.hypothesis_type]
    quarantine = [{"raw_payload": {"kind": "waf decision logs"}}]

    evidence = collect_evidence(hypothesis, events, entry, quarantine)
    waf = [item for item in evidence if item.reason_code.endswith("WAF_DECISION_LOGS")]

    assert len(waf) == 1
    assert waf[0].kind is EvidenceKind.MISSING
    assert waf[0].source_event_id is None
