"""Deterministic historical-incident lookups for RCA similarity scoring."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.rca.contracts import HistoricalMatch


_NON_FEATURE_KEYS = frozenset({"same_confirmed_cause", "similarity"})


class HistoricalIncidentRepository:
    """Read-only incident memory with exact, explainable matching rules."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[models.HistoricalIncident]:
        stmt = select(models.HistoricalIncident).order_by(models.HistoricalIncident.id)
        return list(self.session.execute(stmt).scalars())

    def list_confirmed_by_cause(
        self, confirmed_cause: str
    ) -> list[models.HistoricalIncident]:
        stmt = (
            select(models.HistoricalIncident)
            .where(models.HistoricalIncident.confirmed_cause == confirmed_cause)
            .order_by(models.HistoricalIncident.id)
        )
        return list(self.session.execute(stmt).scalars())

    def find_similarity_matches(
        self,
        *,
        candidate_cause: str,
        fingerprint: str,
        feature_vector: Mapping[str, Any],
    ) -> list[HistoricalMatch]:
        """Score every row without fuzzy text or hidden heuristics.

        A cause mismatch always scores zero. For a matching cause, an exact
        fingerprint scores one; otherwise matching at least half of the
        historical row's declared feature keys scores one half.
        """

        matches = [
            HistoricalMatch(
                historical_incident_id=row.id,
                fingerprint=row.fingerprint,
                confirmed_cause=row.confirmed_cause,
                summary=row.summary,
                feature_vector=dict(row.feature_vector),
                similarity=self._similarity(
                    row,
                    candidate_cause=candidate_cause,
                    fingerprint=fingerprint,
                    feature_vector=feature_vector,
                ),
            )
            for row in self.list_all()
        ]
        return sorted(
            matches,
            key=lambda item: (-item.similarity, item.historical_incident_id),
        )

    @staticmethod
    def _similarity(
        row: models.HistoricalIncident,
        *,
        candidate_cause: str,
        fingerprint: str,
        feature_vector: Mapping[str, Any],
    ) -> float:
        if row.confirmed_cause != candidate_cause:
            return 0.0
        if row.fingerprint == fingerprint:
            return 1.0
        expected = {
            key: value
            for key, value in row.feature_vector.items()
            if key not in _NON_FEATURE_KEYS
        }
        if not expected:
            return 0.0
        matching = sum(feature_vector.get(key) == value for key, value in expected.items())
        return 0.5 if matching * 2 >= len(expected) else 0.0


__all__ = ["HistoricalIncidentRepository"]
