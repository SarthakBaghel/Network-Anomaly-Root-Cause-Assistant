from pathlib import Path

import pytest
import yaml

from app.playbooks import engine
from app.playbooks.engine import (
    PlaybookRecommendation,
    PlaybookValidationError,
    get_recommendations,
)

HYPOTHESES_FILE = Path(__file__).resolve().parents[2] / "app" / "fixtures" / "hypotheses.yaml"


def test_recommendation_lookup_works():
    recs = get_recommendations("configuration_regression", "gateway")

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
        assert "gateway" in rec.applicable_entity_types


def test_db_and_dos_lookups_return_expected_steps():
    db = {r.step_id for r in get_recommendations("database_connection_exhaustion", "database")}
    assert {"inspect-db-pool", "propose-db-pool-tuning"} <= db

    dos = {r.step_id for r in get_recommendations("dos_or_traffic_surge", "gateway")}
    assert {"inspect-ingress-distribution", "propose-edge-rate-limit"} <= dos


def test_unknown_hypothesis_returns_empty_list():
    assert get_recommendations("totally_unknown_type", "service") == []


def test_entity_type_must_also_match():
    # Known hypothesis but non-applicable entity type -> no matches.
    assert get_recommendations("database_connection_exhaustion", "router") == []


def test_every_catalogue_step_requires_human_approval():
    all_recs = engine.load_recommendations()

    assert all_recs, "expected a non-empty catalogue"
    for rec in all_recs:
        assert rec.requires_human_approval is True


def test_every_hypothesis_has_matching_catalogue_step():
    with HYPOTHESES_FILE.open(encoding="utf-8") as fixture:
        hypotheses = yaml.safe_load(fixture)["hypotheses"]

    catalogue = engine.load_recommendations()
    catalogue_step_ids = {rec.step_id for rec in catalogue}
    for hypothesis in hypotheses:
        hypothesis_type = hypothesis["hypothesis_type"]
        matching = [
            rec
            for rec in catalogue
            if hypothesis_type in rec.applicable_hypothesis_types
        ]
        assert matching, f"{hypothesis_type} has no matching catalogue step"

        expected_step_ids = set(hypothesis["diagnostic_step_ids"])
        expected_step_ids.update(hypothesis["remediation_step_ids"])
        assert expected_step_ids <= catalogue_step_ids


def test_instructions_are_lists():
    for rec in engine.load_recommendations():
        assert isinstance(rec.instructions, list)
        assert all(isinstance(line, str) for line in rec.instructions)


def test_step_types_are_diagnostic_or_remediation():
    for rec in engine.load_recommendations():
        assert rec.step_type in ("diagnostic", "remediation")


def test_validation_raises_when_any_step_is_missing_approval():
    bad = [
        PlaybookRecommendation(
            step_id="bad-diagnostic",
            title="Bad diagnostic",
            step_type="diagnostic",
            applicable_hypothesis_types=["configuration_regression"],
            applicable_entity_types=["service"],
            preconditions=[],
            instructions=["do something"],
            risk_level="low",
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
