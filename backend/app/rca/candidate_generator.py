"""Catalogue-only root-cause candidate generation (blueprint §14.1–14.2)."""

from __future__ import annotations

from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.contracts import CanonicalEvent, Modality, TopologyRelation

from .contracts import HypothesisCandidate, IncidentAnalysisBundle


CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "hypotheses.yaml"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})


class RcaDomainError(ValueError):
    """Base class for sanitized deterministic RCA failures."""


class CatalogueValidationError(RcaDomainError):
    """The checked-in hypothesis catalogue is malformed or unsupported."""


class CandidateGenerationError(RcaDomainError):
    """Candidate generation could not safely evaluate canonical input."""


class TraversalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relation_type: TopologyRelation
    direction: Literal["forward", "reverse"]
    max_hops: int = Field(ge=1)


class GenerationRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_selector: Literal[
        "changed_entity", "primary_entity", "referenced_dependency", "event_entity"
    ]
    requires_recent_change: bool = False
    any_anomaly_types: tuple[str, ...] = ()
    any_log_event_types: tuple[str, ...] = ()
    any_event_types: tuple[str, ...] = ()
    referenced_entity_types: tuple[str, ...] = ()


class ConflictPattern(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern_id: str = Field(min_length=1)
    factor: str = Field(min_length=1)
    operation: Literal["subtract", "cap"]
    value: float = Field(ge=0.0, le=1.0)
    match: dict[str, Any]
    statement: str = Field(min_length=1)


class HypothesisDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hypothesis_type: str = Field(min_length=1)
    entity_types: tuple[str, ...] = Field(min_length=1)
    traversal: TraversalPolicy
    generation: GenerationRule
    change_based: bool
    plausible_change_keys: tuple[str, ...] = ()
    topology_origin_event_types: tuple[str, ...] = ()
    metric_anomaly_types: tuple[str, ...] = ()
    required_symptoms: tuple[str, ...]
    expected_propagation: tuple[str, ...]
    expected_evidence: dict[str, str]
    conflict_patterns: tuple[ConflictPattern, ...]
    summary: str = Field(min_length=1)
    diagnostic_step_ids: tuple[str, ...]
    remediation_step_ids: tuple[str, ...]


class HypothesisCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    version: str = Field(min_length=1)
    pattern_definitions: dict[str, dict[str, dict[str, Any]]]
    hypotheses: tuple[HypothesisDefinition, ...]

    @model_validator(mode="after")
    def validate_catalogue_graph(self) -> "HypothesisCatalogue":
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("unsupported hypothesis catalogue schema")
        types = [item.hypothesis_type for item in self.hypotheses]
        if len(set(types)) != len(types):
            raise ValueError("hypothesis types must be unique")
        symptoms = set(self.pattern_definitions.get("symptoms", {}))
        propagation = set(self.pattern_definitions.get("propagation", {}))
        for entry in self.hypotheses:
            if not set(entry.required_symptoms).issubset(symptoms):
                raise ValueError("hypothesis references an unknown symptom pattern")
            if not set(entry.expected_propagation).issubset(propagation):
                raise ValueError("hypothesis references an unknown propagation pattern")
        return self

    def entry(self, hypothesis_type: str) -> HypothesisDefinition:
        for item in self.hypotheses:
            if item.hypothesis_type == hypothesis_type:
                return item
        raise CatalogueValidationError("candidate type is not present in the catalogue")


@lru_cache(maxsize=1)
def load_hypothesis_catalogue(
    path: Path = CATALOGUE_PATH,
) -> HypothesisCatalogue:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("catalogue root must be an object")
        return HypothesisCatalogue.model_validate(payload)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        raise CatalogueValidationError("hypothesis catalogue validation failed") from exc


def _typed_path_exists(
    bundle: IncidentAnalysisBundle,
    source: str,
    target: str,
    policy: TraversalPolicy,
) -> bool:
    if source == target:
        return True
    adjacency: dict[str, list[str]] = {}
    for edge in bundle.topology.edges:
        if edge.relation_type != policy.relation_type:
            continue
        start, end = (
            (edge.source, edge.target)
            if policy.direction == "forward"
            else (edge.target, edge.source)
        )
        adjacency.setdefault(start, []).append(end)
    queue = deque([(source, 0)])
    visited = {source}
    while queue:
        current, distance = queue.popleft()
        if distance >= policy.max_hops:
            continue
        for neighbor in adjacency.get(current, []):
            if neighbor == target:
                return True
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, distance + 1))
    return False


class CandidateGenerator:
    """Generate only candidates whose checked-in catalogue rules match."""

    def __init__(self, catalogue: HypothesisCatalogue | None = None) -> None:
        self.catalogue = catalogue or load_hypothesis_catalogue()

    def generate(self, bundle: IncidentAnalysisBundle) -> tuple[HypothesisCandidate, ...]:
        anomaly_types = {item.anomaly_type for item in bundle.anomalies}
        node_types = {node.entity_id: node.entity_type for node in bundle.topology.nodes}
        generated: list[HypothesisCandidate] = []

        for entry in self.catalogue.hypotheses:
            matched_events = self._generation_events(entry, bundle, anomaly_types)
            if matched_events is None:
                continue
            selected = self._select_entities(entry, bundle, matched_events)
            for entity_id, selector_reason in selected:
                entity_type = node_types.get(entity_id)
                if entity_type not in entry.entity_types:
                    continue
                origins = bundle.incident.affected_entity_ids or (
                    bundle.incident.primary_entity_id,
                )
                if not any(
                    _typed_path_exists(bundle, origin, entity_id, entry.traversal)
                    for origin in origins
                ):
                    continue
                reasons = [selector_reason, "TOPOLOGY_ENTITY_TYPE_MATCH"]
                if entry.generation.any_anomaly_types:
                    reasons.append("ANOMALY_TYPE_MATCH")
                if entry.generation.any_log_event_types:
                    reasons.append("LOG_PATTERN_MATCH")
                if entry.generation.requires_recent_change:
                    reasons.append("RECENT_CHANGE_MATCH")
                reasons.append("TYPED_TOPOLOGY_LOCATION_MATCH")
                generated.append(
                    HypothesisCandidate(
                        candidate_id=f"candidate_{len(generated) + 1:03d}",
                        hypothesis_type=entry.hypothesis_type,
                        candidate_entity_id=entity_id,
                        generation_reason_codes=tuple(dict.fromkeys(reasons)),
                    )
                )
                break
        return tuple(generated)

    def _generation_events(
        self,
        entry: HypothesisDefinition,
        bundle: IncidentAnalysisBundle,
        anomaly_types: set[str],
    ) -> tuple[CanonicalEvent, ...] | None:
        rules = entry.generation
        if rules.requires_recent_change and not any(
            event.modality is Modality.CONFIG_CHANGE
            for event in bundle.attached_events
        ):
            return None
        anomaly_match = bool(
            set(rules.any_anomaly_types).intersection(anomaly_types)
        )
        log_matches = tuple(
            event
            for event in bundle.attached_events
            if event.modality is Modality.LOG
            and event.event_type in rules.any_log_event_types
        )
        event_matches = tuple(
            event
            for event in bundle.attached_events
            if event.event_type in rules.any_event_types
        )
        signal_rules_present = bool(
            rules.any_anomaly_types
            or rules.any_log_event_types
            or rules.any_event_types
        )
        if signal_rules_present and not (anomaly_match or log_matches or event_matches):
            return None
        events_by_id = {
            event.event_id: event for event in bundle.attached_events
        }
        anomaly_events = tuple(
            events_by_id[anomaly.event_id]
            for anomaly in bundle.anomalies
            if anomaly.anomaly_type in rules.any_anomaly_types
            and anomaly.event_id in events_by_id
        )
        combined = {
            event.event_id: event
            for event in (*anomaly_events, *log_matches, *event_matches)
        }
        return tuple(
            sorted(combined.values(), key=lambda event: (event.timestamp, event.event_id))
        )

    def _select_entities(
        self,
        entry: HypothesisDefinition,
        bundle: IncidentAnalysisBundle,
        matched_events: tuple[CanonicalEvent, ...],
    ) -> tuple[tuple[str, str], ...]:
        selector = entry.generation.candidate_selector
        if selector == "primary_entity":
            return ((bundle.incident.primary_entity_id, "PRIMARY_ENTITY_SELECTED"),)
        if selector == "changed_entity":
            changes = sorted(
                (
                    event
                    for event in bundle.attached_events
                    if event.modality is Modality.CONFIG_CHANGE
                ),
                key=lambda event: (event.timestamp, event.event_id),
            )
            return tuple(
                (
                    str(event.raw_payload.get("target_entity_id") or event.entity_id),
                    "CHANGED_ENTITY_SELECTED",
                )
                for event in changes
            )
        if selector == "event_entity":
            return tuple(
                (event.entity_id, "MATCHING_EVENT_ENTITY_SELECTED")
                for event in matched_events
            )
        if selector == "referenced_dependency":
            selected: list[tuple[str, str]] = []
            for event in matched_events:
                dependency_id = event.raw_payload.get("dependency_id")
                if isinstance(dependency_id, str):
                    selected.append((dependency_id, "REFERENCED_DEPENDENCY_SELECTED"))
            return tuple(selected)
        raise CandidateGenerationError("unsupported candidate selector")


candidate_generator = CandidateGenerator()


__all__ = [
    "CandidateGenerationError",
    "CandidateGenerator",
    "CatalogueValidationError",
    "ConflictPattern",
    "GenerationRule",
    "HypothesisCatalogue",
    "HypothesisDefinition",
    "RcaDomainError",
    "TraversalPolicy",
    "candidate_generator",
    "load_hypothesis_catalogue",
]
