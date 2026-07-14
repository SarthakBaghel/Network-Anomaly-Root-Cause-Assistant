from __future__ import annotations

from pydantic import Field, model_validator

from .base import FrozenModel


FACTOR_NAMES = {
    "symptom_compatibility",
    "topology_relevance",
    "direct_logs_alerts",
    "propagation_consistency",
    "metric_anomaly",
    "change_causal_fit",
    "temporal_proximity",
    "historical_similarity",
}


class EvidenceCoverage(FrozenModel):
    available: int = Field(ge=0)
    expected: int = Field(ge=0)

    @model_validator(mode="after")
    def available_does_not_exceed_expected(self) -> "EvidenceCoverage":
        if self.available > self.expected:
            raise ValueError("available evidence cannot exceed expected evidence")
        return self


class Hypothesis(FrozenModel):
    hypothesis_id: str = Field(min_length=1)
    analysis_run_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    hypothesis_type: str = Field(min_length=1)
    candidate_entity_id: str = Field(min_length=1)
    rank: int = Field(ge=1)
    evidence_score: float = Field(ge=0.0, le=100.0)
    evidence_coverage: EvidenceCoverage
    factor_scores: dict[str, float]
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_factor_scores(self) -> "Hypothesis":
        if set(self.factor_scores) != FACTOR_NAMES:
            raise ValueError(f"factor_scores must contain exactly {sorted(FACTOR_NAMES)}")
        if any(value < 0.0 or value > 1.0 for value in self.factor_scores.values()):
            raise ValueError("factor scores must be between 0.0 and 1.0")
        return self

