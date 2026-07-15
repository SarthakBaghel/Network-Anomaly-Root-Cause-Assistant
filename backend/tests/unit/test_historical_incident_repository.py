from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import models
from app.db.repositories import HistoricalIncidentRepository


def _session() -> Session:
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    return Session(engine)


def _row(identifier: str, fingerprint: str, cause: str) -> models.HistoricalIncident:
    return models.HistoricalIncident(
        id=identifier,
        fingerprint=fingerprint,
        confirmed_cause=cause,
        summary=f"Historical {identifier}",
        feature_vector={
            "entity_type": "gateway",
            "change_type": "rate_limit.enabled",
            "forwarded_traffic_spike": True,
        },
    )


def test_seeded_partial_match_is_half_and_exact_match_is_one() -> None:
    with _session() as session:
        session.add(_row("hist_b", "fp_exact", "configuration_regression"))
        session.commit()
        repository = HistoricalIncidentRepository(session)
        features = {
            "entity_type": "gateway",
            "change_type": "rate_limit.enabled",
        }

        partial = repository.find_similarity_matches(
            candidate_cause="configuration_regression",
            fingerprint="different",
            feature_vector=features,
        )
        exact = repository.find_similarity_matches(
            candidate_cause="configuration_regression",
            fingerprint="fp_exact",
            feature_vector={},
        )

        assert partial[0].similarity == 0.5
        assert exact[0].similarity == 1.0


def test_different_cause_scores_zero_and_order_is_stable() -> None:
    with _session() as session:
        session.add_all(
            [
                _row("hist_b", "fp_b", "configuration_regression"),
                _row("hist_a", "fp_a", "configuration_regression"),
            ]
        )
        session.commit()
        repository = HistoricalIncidentRepository(session)

        first = repository.find_similarity_matches(
            candidate_cause="dos_or_traffic_surge",
            fingerprint="fp_a",
            feature_vector={"entity_type": "gateway"},
        )
        second = repository.find_similarity_matches(
            candidate_cause="dos_or_traffic_surge",
            fingerprint="fp_a",
            feature_vector={"entity_type": "gateway"},
        )

        assert [item.similarity for item in first] == [0.0, 0.0]
        assert [item.historical_incident_id for item in first] == ["hist_a", "hist_b"]
        assert first == second
        assert [item.id for item in repository.list_confirmed_by_cause(
            "configuration_regression"
        )] == ["hist_a", "hist_b"]


def test_empty_history_returns_no_matches() -> None:
    with _session() as session:
        assert HistoricalIncidentRepository(session).find_similarity_matches(
            candidate_cause="configuration_regression",
            fingerprint="none",
            feature_vector={},
        ) == []
