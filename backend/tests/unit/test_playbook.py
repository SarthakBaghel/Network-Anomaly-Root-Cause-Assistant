import pytest

from app.playbooks import engine
from app.playbooks.engine import (
    PlaybookRecommendation,
    PlaybookValidationError,
    get_recommendations,
)


def test_recommendation_lookup_works():
    recs = get_recommendations("configuration_regression", "service")

    assert recs, "expected at least one recommendation"
    assert all(isinstance(r, PlaybookRecommendation) for r in recs)

    step_ids = {r.step_id for r in recs}
    assert {
        "inspect-config-diff",
        "compare-pre-post-metrics",
        "propose-config-rollback",
    } <= step_ids

    for rec in recs:
        assert "configuration_regression" in rec.applicable_hypothesis_types
        assert "service" in rec.applicable_entity_types


def test_db_and_dos_lookups_return_expected_steps():
    db = {r.step_id for r in get_recommendations("database_connection_exhaustion", "database")}
    assert {"inspect-db-connections", "review-query-latency"} <= db

    dos = {r.step_id for r in get_recommendations("dos_or_traffic_surge", "load_balancer")}
    assert {"inspect-ingress-patterns", "validate-source-distribution"} <= dos

    authorized_scanner = {
        recommendation.step_id
        for recommendation in get_recommendations("authorized_security_scanner", "gateway")
    }
    assert authorized_scanner == {
        "inspect-scan-pattern",
        "verify-scanner-authorization",
    }


def test_unknown_hypothesis_returns_empty_list():
    assert get_recommendations("totally_unknown_type", "service") == []


def test_entity_type_must_also_match():
    # Known hypothesis but non-applicable entity type -> no matches.
    assert get_recommendations("database_connection_exhaustion", "router") == []


def test_remediation_steps_require_human_approval():
    all_recs = engine.load_recommendations()
    remediation = [r for r in all_recs if r.step_type == "remediation"]

    assert remediation, "expected at least one remediation step in fixtures"
    for rec in remediation:
        assert rec.requires_human_approval is True


def test_every_catalogue_step_requires_human_approval():
    assert all(
        recommendation.requires_human_approval for recommendation in engine.load_recommendations()
    )


def test_instructions_are_lists():
    for rec in engine.load_recommendations():
        assert isinstance(rec.instructions, list)
        assert all(isinstance(line, str) for line in rec.instructions)


def test_step_types_are_diagnostic_or_remediation():
    for rec in engine.load_recommendations():
        assert rec.step_type in ("diagnostic", "remediation")


def test_validation_raises_when_remediation_missing_approval():
    bad = [
        PlaybookRecommendation(
            step_id="bad-remediation",
            title="Bad remediation",
            step_type="remediation",
            applicable_hypothesis_types=["configuration_regression"],
            applicable_entity_types=["service"],
            preconditions=[],
            instructions=["do something risky"],
            risk_level="high",
            rollback_note=None,
            requires_human_approval=False,
        )
    ]

    with pytest.raises(PlaybookValidationError):
        engine._validate_recommendations(bad)


def test_unknown_step_type_fails_startup_validation():
    # Bypass model validation to simulate a malformed fixture reaching the
    # startup safety check.
    bad = [
        PlaybookRecommendation.model_construct(
            step_id="bad-step-type",
            title="Bad step type",
            step_type="inspection",
            applicable_hypothesis_types=["configuration_regression"],
            applicable_entity_types=["service"],
            preconditions=[],
            instructions=["do a thing"],
            risk_level="low",
            rollback_note=None,
            requires_human_approval=False,
        )
    ]

    with pytest.raises(PlaybookValidationError):
        engine._validate_recommendations(bad)
