"""Immutable, database-free contracts at the Person 1/Person 4 RCA boundary.

Only canonical contracts and plain values are allowed in this module. In
particular, importing SQLAlchemy or ORM models here would make deterministic
RCA computation depend on persistence state.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts import AnomalyRecord, CanonicalEvent, EvidenceCoverage, TopologyRelation


class RcaBoundaryModel(BaseModel):
    """Strict, immutable value model used by the pure RCA boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def canonical_json(self) -> str:
        """Return a byte-stable representation for determinism tests."""

        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )


class IncidentSnapshot(RcaBoundaryModel):
    incident_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: Literal["open", "investigating", "resolved", "rejected"]
    severity: float = Field(ge=0.0, le=1.0)
    started_at: datetime
    last_event_at: datetime
    primary_entity_id: str = Field(min_length=1)
    primary_entity_type: str = Field(min_length=1)
    affected_entity_ids: tuple[str, ...]
    anomaly_count: int = Field(ge=0)


class EventEvaluation(RcaBoundaryModel):
    """An evaluated-but-excluded event, kept outside incident evidence."""

    event: CanonicalEvent
    decision: Literal["excluded"] = "excluded"
    attachment_score: float
    attachment_reasons: tuple[str, ...]


class RcaTopologyNode(RcaBoundaryModel):
    entity_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    service: str = Field(min_length=1)
    criticality: str = Field(min_length=1)


class RcaTopologyEdge(RcaBoundaryModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation_type: TopologyRelation
    relationship: str = Field(min_length=1)


class RcaTopologySnapshot(RcaBoundaryModel):
    fixture_version: str = Field(min_length=1)
    nodes: tuple[RcaTopologyNode, ...]
    edges: tuple[RcaTopologyEdge, ...]

    @model_validator(mode="after")
    def validate_edges(self) -> "RcaTopologySnapshot":
        node_ids = {node.entity_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("topology node IDs must be unique")
        for edge in self.edges:
            if edge.source == edge.target:
                raise ValueError("topology self-edges are not allowed")
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError("topology edge endpoint does not resolve")
        return self


class HistoricalMatch(RcaBoundaryModel):
    historical_incident_id: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    confirmed_cause: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    feature_vector: dict[str, Any]
    similarity: float = Field(ge=0.0, le=1.0)


class IncidentAnalysisBundle(RcaBoundaryModel):
    """Complete, ordered input accepted by the pure Person 4 engine."""

    incident: IncidentSnapshot
    attached_events: tuple[CanonicalEvent, ...]
    anomalies: tuple[AnomalyRecord, ...]
    excluded_evaluations: tuple[EventEvaluation, ...]
    topology: RcaTopologySnapshot
    historical_matches: tuple[HistoricalMatch, ...]

    @model_validator(mode="after")
    def validate_event_partitions(self) -> "IncidentAnalysisBundle":
        attached_ids = [event.event_id for event in self.attached_events]
        attached_set = set(attached_ids)
        if len(attached_set) != len(attached_ids):
            raise ValueError("attached event IDs must be unique")
        excluded_ids = [item.event.event_id for item in self.excluded_evaluations]
        if attached_set.intersection(excluded_ids):
            raise ValueError("an excluded event cannot be attached")
        if any(anomaly.event_id not in attached_set for anomaly in self.anomalies):
            raise ValueError("incident anomalies must reference attached events")
        return self


class HypothesisCandidate(RcaBoundaryModel):
    candidate_id: str = Field(min_length=1)
    hypothesis_type: str = Field(min_length=1)
    candidate_entity_id: str = Field(min_length=1)
    generation_reason_codes: tuple[str, ...] = ()


class RankedHypothesis(RcaBoundaryModel):
    hypothesis_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    hypothesis_type: str = Field(min_length=1)
    candidate_entity_id: str = Field(min_length=1)
    rank: int = Field(ge=1)
    evidence_score: float = Field(ge=0.0, le=100.0)
    evidence_coverage: EvidenceCoverage
    factor_scores: dict[str, float]
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_factors(self) -> "RankedHypothesis":
        if any(value < 0.0 or value > 1.0 for value in self.factor_scores.values()):
            raise ValueError("factor scores must be between 0.0 and 1.0")
        return self


class ConflictEvidenceDraft(RcaBoundaryModel):
    """Run-agnostic conflict evidence; the adapter binds run/incident IDs."""

    hypothesis_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    relevance: float = Field(ge=0.0, le=1.0)
    reason_code: str = Field(min_length=1)


class TopologyNodeState(RcaBoundaryModel):
    entity_id: str = Field(min_length=1)
    state: Literal["suspected_root", "primary_affected", "impact_path", "blast_radius"]


class TopologyEdgeState(RcaBoundaryModel):
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    relation_type: TopologyRelation
    state: Literal["impact_path", "blast_radius"]


class TopologyStates(RcaBoundaryModel):
    nodes: tuple[TopologyNodeState, ...] = ()
    edges: tuple[TopologyEdgeState, ...] = ()


class RcaComputationResult(RcaBoundaryModel):
    """Pure computation output before run-scoped persistence mapping."""

    candidates: tuple[HypothesisCandidate, ...]
    ranked_hypotheses: tuple[RankedHypothesis, ...]
    conflict_evidence: tuple[ConflictEvidenceDraft, ...] = ()
    conflict_reason_codes: tuple[str, ...] = ()
    topology_states: TopologyStates = Field(default_factory=TopologyStates)
    typed_paths: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    evidence_requirements: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result_graph(self) -> "RcaComputationResult":
        candidates = {item.candidate_id: item for item in self.candidates}
        if len(candidates) != len(self.candidates):
            raise ValueError("candidate IDs must be unique")
        hypothesis_ids = {item.hypothesis_id for item in self.ranked_hypotheses}
        if len(hypothesis_ids) != len(self.ranked_hypotheses):
            raise ValueError("hypothesis IDs must be unique")
        ranks = sorted(item.rank for item in self.ranked_hypotheses)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("hypothesis ranks must be unique and consecutive")
        for ranked in self.ranked_hypotheses:
            candidate = candidates.get(ranked.candidate_id)
            if candidate is None:
                raise ValueError("ranked hypothesis references an unknown candidate")
            if (
                candidate.hypothesis_type != ranked.hypothesis_type
                or candidate.candidate_entity_id != ranked.candidate_entity_id
            ):
                raise ValueError("ranked hypothesis does not match its candidate")
        for conflict in self.conflict_evidence:
            if conflict.hypothesis_id not in hypothesis_ids:
                raise ValueError("conflict evidence references an unknown hypothesis")
        draft_codes = tuple(dict.fromkeys(item.reason_code for item in self.conflict_evidence))
        if tuple(self.conflict_reason_codes) != draft_codes:
            raise ValueError("conflict reason codes must match conflict evidence order")
        valid_requirement_keys = hypothesis_ids | {
            item.hypothesis_type for item in self.ranked_hypotheses
        }
        if not set(self.evidence_requirements).issubset(valid_requirement_keys):
            raise ValueError("evidence requirements reference an unknown hypothesis")
        if any(len(path) < 1 for path in self.typed_paths.values()):
            raise ValueError("typed topology paths cannot be empty")
        return self


__all__ = [
    "ConflictEvidenceDraft",
    "EventEvaluation",
    "HistoricalMatch",
    "HypothesisCandidate",
    "IncidentAnalysisBundle",
    "IncidentSnapshot",
    "RankedHypothesis",
    "RcaComputationResult",
    "RcaTopologyEdge",
    "RcaTopologyNode",
    "RcaTopologySnapshot",
    "TopologyEdgeState",
    "TopologyNodeState",
    "TopologyStates",
]
