from __future__ import annotations

from decimal import Decimal

from app.rca import (
    CandidateGenerator,
    RootCauseRanker,
    load_hypothesis_catalogue,
    round_half_up,
    score_factors,
)
from app.rca.candidate_generator import HypothesisCatalogue
from app.rca.ranker import WEIGHTS
from tests.support.rca_prerequisites import build_golden_analysis_bundle


def _ranked():
    bundle = build_golden_analysis_bundle()
    candidates = CandidateGenerator().generate(bundle)
    return RootCauseRanker().rank(candidates, bundle)


def test_golden_scores_and_rank_order() -> None:
    ranked = _ranked()

    assert [item.candidate.hypothesis_type for item in ranked] == [
        "configuration_regression",
        "dos_or_traffic_surge",
        "database_connection_exhaustion",
    ]
    assert [item.evidence_score for item in ranked] == [92.1, 65.6, 41.5]


def test_decimal_half_up_and_missing_factors_are_not_renormalized() -> None:
    assert sum(WEIGHTS.values()) == Decimal("1.00")
    assert round_half_up(Decimal("92.10")) == 92.1
    assert round_half_up(Decimal("92.15")) == 92.2
    assert score_factors({}) == 0.0
    assert score_factors({"symptom_compatibility": 1.0}) == 25.0


def test_dos_stable_ingress_conflict_does_not_double_penalize() -> None:
    dos = next(
        item for item in _ranked() if item.candidate.hypothesis_type == "dos_or_traffic_surge"
    )

    assert dos.factor_scores["symptom_compatibility"] == 0.5
    assert dos.factor_scores["change_causal_fit"] == 0.0
    assert dos.factor_scores["temporal_proximity"] == 0.0
    conflict = next(item for item in dos.conflicts if item.pattern_id == "STABLE_RAW_INGRESS")
    assert conflict.factor == "symptom_compatibility"
    assert conflict.operation == "cap"
    assert conflict.value == 0.5
    assert conflict.source_event_id


def test_normal_database_utilization_caps_metric_factor_and_emits_conflict() -> None:
    database = next(
        item
        for item in _ranked()
        if item.candidate.hypothesis_type == "database_connection_exhaustion"
    )

    assert database.factor_scores["metric_anomaly"] == 0.0
    assert database.factor_scores["topology_relevance"] == 0.5
    assert database.factor_scores["propagation_consistency"] == 0.6667
    conflict = next(
        item for item in database.conflicts if item.pattern_id == "NORMAL_DB_UTILIZATION"
    )
    assert conflict.factor == "metric_anomaly"
    assert conflict.source_event_id


def test_conflict_effects_apply_in_catalogue_order_with_subtract_support() -> None:
    bundle = build_golden_analysis_bundle()
    payload = load_hypothesis_catalogue().model_dump(mode="json")
    dos = next(
        item
        for item in payload["hypotheses"]
        if item["hypothesis_type"] == "dos_or_traffic_surge"
    )
    dos["conflict_patterns"].append(
        {
            "pattern_id": "SECOND_STABLE_INGRESS_EFFECT",
            "factor": "symptom_compatibility",
            "operation": "subtract",
            "value": 0.1,
            "match": {
                "event_types": ["RAW_INGRESS_RATE"],
                "absent_anomaly_types": ["RAW_INGRESS_SPIKE"],
            },
            "statement": "A second catalogue conflict effect was applied.",
        }
    )
    catalogue = HypothesisCatalogue.model_validate(payload)
    candidates = CandidateGenerator(catalogue).generate(bundle)
    dos_candidate = next(
        item for item in candidates if item.hypothesis_type == "dos_or_traffic_surge"
    )
    scored = RootCauseRanker(catalogue).score_candidate(dos_candidate, bundle)

    assert scored.factor_scores["symptom_compatibility"] == 0.4
    assert [item.pattern_id for item in scored.conflicts] == [
        "STABLE_RAW_INGRESS",
        "SECOND_STABLE_INGRESS_EFFECT",
    ]
