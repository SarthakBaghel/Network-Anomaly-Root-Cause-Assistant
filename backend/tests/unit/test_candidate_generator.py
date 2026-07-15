from __future__ import annotations

from app.rca import CandidateGenerator, load_hypothesis_catalogue
from tests.support.rca_prerequisites import build_golden_analysis_bundle


def test_golden_bundle_generates_exactly_three_catalogue_candidates() -> None:
    catalogue = load_hypothesis_catalogue()
    candidates = CandidateGenerator(catalogue).generate(build_golden_analysis_bundle())

    assert [item.hypothesis_type for item in candidates] == [
        "configuration_regression",
        "dos_or_traffic_surge",
        "database_connection_exhaustion",
    ]
    assert [item.candidate_entity_id for item in candidates] == [
        "api-gateway-01",
        "api-gateway-01",
        "payment-db-01",
    ]
    assert {item.hypothesis_type for item in candidates}.issubset(
        {entry.hypothesis_type for entry in catalogue.hypotheses}
    )


def test_generation_reasons_cover_change_anomaly_log_entity_and_topology() -> None:
    candidates = CandidateGenerator().generate(build_golden_analysis_bundle())
    by_type = {item.hypothesis_type: item for item in candidates}

    assert set(by_type["configuration_regression"].generation_reason_codes).issuperset(
        {
            "CHANGED_ENTITY_SELECTED",
            "ANOMALY_TYPE_MATCH",
            "RECENT_CHANGE_MATCH",
            "TOPOLOGY_ENTITY_TYPE_MATCH",
            "TYPED_TOPOLOGY_LOCATION_MATCH",
        }
    )
    assert set(
        by_type["database_connection_exhaustion"].generation_reason_codes
    ).issuperset(
        {
            "REFERENCED_DEPENDENCY_SELECTED",
            "LOG_PATTERN_MATCH",
            "TOPOLOGY_ENTITY_TYPE_MATCH",
            "TYPED_TOPOLOGY_LOCATION_MATCH",
        }
    )
