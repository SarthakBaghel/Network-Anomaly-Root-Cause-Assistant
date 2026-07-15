"""Deterministic evidence scoring and catalogue conflict effects."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.contracts import CanonicalEvent, EvidenceCoverage, Modality

from .candidate_generator import (
    ConflictPattern,
    HypothesisCatalogue,
    HypothesisDefinition,
    RcaDomainError,
    TraversalPolicy,
    load_hypothesis_catalogue,
)
from .contracts import HypothesisCandidate, IncidentAnalysisBundle


WEIGHTS: dict[str, Decimal] = {
    "symptom_compatibility": Decimal("0.25"),
    "topology_relevance": Decimal("0.20"),
    "direct_logs_alerts": Decimal("0.15"),
    "propagation_consistency": Decimal("0.15"),
    "metric_anomaly": Decimal("0.10"),
    "change_causal_fit": Decimal("0.10"),
    "temporal_proximity": Decimal("0.03"),
    "historical_similarity": Decimal("0.02"),
}
WEIGHT_VALUES = {name: float(value) for name, value in WEIGHTS.items()}


class RankingError(RcaDomainError):
    """Canonical input could not be scored using the frozen rubric."""


@dataclass(frozen=True)
class AppliedConflict:
    pattern_id: str
    factor: str
    operation: str
    value: float
    source_event_id: str
    statement: str
    relevance: float = 0.95


@dataclass(frozen=True)
class CandidateScore:
    candidate: HypothesisCandidate
    factor_scores: dict[str, float]
    evidence_score: float
    evidence_coverage: EvidenceCoverage
    conflicts: tuple[AppliedConflict, ...]
    topology_origin: str | None
    topology_path: tuple[str, ...]


def round_half_up(value: Decimal | float | str, places: int = 1) -> float:
    quantizer = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP))


def score_factors(factors: dict[str, float]) -> float:
    """Score known factors; missing factors are zero and are not renormalized."""

    unknown = set(factors).difference(WEIGHTS)
    if unknown:
        raise RankingError("factor input contains an unsupported factor")
    weighted = sum(
        weight * Decimal(str(factors.get(name, 0.0)))
        for name, weight in WEIGHTS.items()
    )
    return round_half_up(Decimal("100") * weighted)


class TopologyIndex:
    """Small deterministic typed traversal view over an immutable bundle."""

    def __init__(self, bundle: IncidentAnalysisBundle) -> None:
        self.node_ids = tuple(node.entity_id for node in bundle.topology.nodes)
        self.edges = bundle.topology.edges

    def path(
        self,
        source: str,
        target: str,
        policy: TraversalPolicy,
    ) -> tuple[str, ...] | None:
        if source == target:
            return (source,)
        adjacency = self._adjacency(policy)
        queue: deque[tuple[str, tuple[str, ...]]] = deque([(source, (source,))])
        visited = {source}
        while queue:
            current, path = queue.popleft()
            if len(path) - 1 >= policy.max_hops:
                continue
            for neighbor in adjacency.get(current, ()):
                next_path = (*path, neighbor)
                if neighbor == target:
                    return next_path
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, next_path))
        return None

    def reachable(
        self,
        source: str,
        policy: TraversalPolicy,
    ) -> tuple[str, ...]:
        adjacency = self._adjacency(policy)
        queue = deque([(source, 0)])
        visited = {source}
        result = [source]
        while queue:
            current, distance = queue.popleft()
            if distance >= policy.max_hops:
                continue
            for neighbor in adjacency.get(current, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    result.append(neighbor)
                    queue.append((neighbor, distance + 1))
        return tuple(result)

    def _adjacency(self, policy: TraversalPolicy) -> dict[str, tuple[str, ...]]:
        mutable: dict[str, list[str]] = {}
        for edge in self.edges:
            if edge.relation_type != policy.relation_type:
                continue
            source, target = (
                (edge.source, edge.target)
                if policy.direction == "forward"
                else (edge.target, edge.source)
            )
            mutable.setdefault(source, []).append(target)
        return {key: tuple(values) for key, values in mutable.items()}


def _event_map(bundle: IncidentAnalysisBundle) -> dict[str, CanonicalEvent]:
    return {event.event_id: event for event in bundle.attached_events}


def _pattern_observations(
    bundle: IncidentAnalysisBundle,
    specification: dict[str, Any],
) -> tuple[CanonicalEvent, ...]:
    events_by_id = _event_map(bundle)
    observed: dict[str, CanonicalEvent] = {}
    anomaly_types = set(specification.get("anomaly_types", ()))
    for anomaly in bundle.anomalies:
        event = events_by_id.get(anomaly.event_id)
        if event is not None and anomaly.anomaly_type in anomaly_types:
            observed[event.event_id] = event

    event_types = set(specification.get("event_types", ()))
    true_keys = tuple(specification.get("raw_payload_true_keys", ()))
    minimum = specification.get("signal_value_gte")
    maximum = specification.get("signal_value_lte")
    for event in bundle.attached_events:
        matches_type = bool(event_types and event.event_type in event_types)
        matches_flag = bool(
            true_keys and any(event.raw_payload.get(key) is True for key in true_keys)
        )
        if not (matches_type or matches_flag):
            continue
        if minimum is not None and (
            event.signal_value is None or event.signal_value < float(minimum)
        ):
            continue
        if maximum is not None and (
            event.signal_value is None or event.signal_value > float(maximum)
        ):
            continue
        observed[event.event_id] = event
    return tuple(
        sorted(observed.values(), key=lambda event: (event.timestamp, event.event_id))
    )


def _recursive_contains(value: Any, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(_recursive_contains(item, expected) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_recursive_contains(item, expected) for item in value)
    return False


def _direct_log_alert_factor(
    bundle: IncidentAnalysisBundle, candidate_entity_id: str
) -> float:
    modalities: set[Modality] = set()
    for event in bundle.attached_events:
        if event.modality not in {Modality.LOG, Modality.ALERT}:
            continue
        if event.entity_id == candidate_entity_id or _recursive_contains(
            event.raw_payload, candidate_entity_id
        ):
            modalities.add(event.modality)
    if {Modality.LOG, Modality.ALERT}.issubset(modalities):
        return 1.0
    return 0.6 if modalities else 0.0


def _ratio(observed: int, declared: int) -> float:
    if declared == 0:
        return 0.0
    return round(observed / declared, 4)


def _topology_origins(
    entry: HypothesisDefinition,
    bundle: IncidentAnalysisBundle,
) -> tuple[str, ...]:
    if entry.topology_origin_event_types:
        origins = tuple(
            dict.fromkeys(
                event.entity_id
                for event in bundle.attached_events
                if event.event_type in entry.topology_origin_event_types
            )
        )
        if origins:
            return origins
    return bundle.incident.affected_entity_ids or (bundle.incident.primary_entity_id,)


def _topology_factor(
    entry: HypothesisDefinition,
    candidate: HypothesisCandidate,
    bundle: IncidentAnalysisBundle,
    topology: TopologyIndex,
) -> tuple[float, str | None, tuple[str, ...]]:
    choices: list[tuple[int, int, str, tuple[str, ...]]] = []
    for order, origin in enumerate(_topology_origins(entry, bundle)):
        path = topology.path(origin, candidate.candidate_entity_id, entry.traversal)
        if path is not None:
            choices.append((len(path) - 1, order, origin, path))
    if not choices:
        return 0.0, None, ()
    distance, _order, origin, path = min(choices)
    factor = {0: 1.0, 1: 0.8, 2: 0.5}.get(distance, 0.0)
    return factor, origin, path


def _propagation_factor(
    entry: HypothesisDefinition,
    catalogue: HypothesisCatalogue,
    bundle: IncidentAnalysisBundle,
) -> float:
    definitions = catalogue.pattern_definitions["propagation"]
    counted = 0
    last_timestamp = None
    for stage in entry.expected_propagation:
        observations = _pattern_observations(bundle, definitions[stage])
        if not observations:
            continue
        timestamp = observations[0].timestamp
        if last_timestamp is None or timestamp >= last_timestamp:
            counted += 1
            last_timestamp = timestamp
    return _ratio(counted, len(entry.expected_propagation))


def _symptom_factor(
    entry: HypothesisDefinition,
    catalogue: HypothesisCatalogue,
    bundle: IncidentAnalysisBundle,
) -> float:
    definitions = catalogue.pattern_definitions["symptoms"]
    observed = sum(
        bool(_pattern_observations(bundle, definitions[symptom]))
        for symptom in entry.required_symptoms
    )
    return _ratio(observed, len(entry.required_symptoms))


def _impact_nodes(
    entry: HypothesisDefinition,
    candidate: HypothesisCandidate,
    topology: TopologyIndex,
    topology_path: tuple[str, ...],
) -> set[str]:
    if entry.traversal.relation_type.value == "sends_traffic_to":
        return set(topology.reachable(candidate.candidate_entity_id, entry.traversal))
    return set(topology_path or (candidate.candidate_entity_id,))


def _metric_anomaly_factor(
    entry: HypothesisDefinition,
    candidate: HypothesisCandidate,
    bundle: IncidentAnalysisBundle,
    topology: TopologyIndex,
    topology_path: tuple[str, ...],
) -> float:
    events = _event_map(bundle)
    applicable_nodes = _impact_nodes(entry, candidate, topology, topology_path)
    scores = [
        anomaly.score
        for anomaly in bundle.anomalies
        if anomaly.anomaly_type in entry.metric_anomaly_types
        and (event := events.get(anomaly.event_id)) is not None
        and event.modality is Modality.METRIC
        and event.entity_id in applicable_nodes
    ]
    return max(scores, default=0.0)


def _first_symptom_event(bundle: IncidentAnalysisBundle) -> CanonicalEvent | None:
    events = _event_map(bundle)
    candidates = [
        events[anomaly.event_id]
        for anomaly in bundle.anomalies
        if not anomaly.context_only and anomaly.event_id in events
    ]
    return min(candidates, key=lambda event: (event.timestamp, event.event_id), default=None)


def _candidate_signal(
    entry: HypothesisDefinition,
    candidate: HypothesisCandidate,
    bundle: IncidentAnalysisBundle,
) -> CanonicalEvent | None:
    if entry.change_based:
        changes = [
            event
            for event in bundle.attached_events
            if event.modality is Modality.CONFIG_CHANGE
            and str(event.raw_payload.get("target_entity_id") or event.entity_id)
            == candidate.candidate_entity_id
        ]
        return min(changes, key=lambda event: (event.timestamp, event.event_id), default=None)

    generation = entry.generation
    events = _event_map(bundle)
    matching: dict[str, CanonicalEvent] = {}
    for anomaly in bundle.anomalies:
        if anomaly.anomaly_type in generation.any_anomaly_types:
            event = events.get(anomaly.event_id)
            if event is not None:
                matching[event.event_id] = event
    for event in bundle.attached_events:
        if event.event_type in (
            *generation.any_log_event_types,
            *generation.any_event_types,
        ):
            matching[event.event_id] = event
    return min(
        matching.values(), key=lambda event: (event.timestamp, event.event_id), default=None
    )


def _temporal_factor(
    signal: CanonicalEvent | None, first_symptom: CanonicalEvent | None
) -> float:
    if signal is None or first_symptom is None or signal.timestamp >= first_symptom.timestamp:
        return 0.0
    seconds = (first_symptom.timestamp - signal.timestamp).total_seconds()
    if seconds <= 60:
        return 1.0
    if seconds <= 180:
        return 0.7
    if seconds <= 300:
        return 0.4
    return 0.0


def _conflict_source(
    pattern: ConflictPattern,
    bundle: IncidentAnalysisBundle,
) -> CanonicalEvent | None:
    absent = set(pattern.match.get("absent_anomaly_types", ()))
    if absent.intersection(anomaly.anomaly_type for anomaly in bundle.anomalies):
        return None
    observations = _pattern_observations(bundle, pattern.match)
    return observations[0] if observations else None


def _change_causal_fit(
    entry: HypothesisDefinition,
    candidate: HypothesisCandidate,
    bundle: IncidentAnalysisBundle,
    topology_path: tuple[str, ...],
    conflicts: tuple[tuple[ConflictPattern, CanonicalEvent], ...],
) -> float:
    if not entry.change_based:
        return 0.0
    first_symptom = _first_symptom_event(bundle)
    change = _candidate_signal(entry, candidate, bundle)
    if change is None:
        return 0.0
    checks = (
        first_symptom is not None and change.timestamp < first_symptom.timestamp,
        str(change.raw_payload.get("target_entity_id") or change.entity_id)
        in set(topology_path or (candidate.candidate_entity_id,)),
        change.raw_payload.get("config_key") in entry.plausible_change_keys,
        not conflicts,
    )
    return sum(bool(check) for check in checks) * 0.25


def _historical_factor(
    entry: HypothesisDefinition, bundle: IncidentAnalysisBundle
) -> float:
    return max(
        (
            match.similarity
            for match in bundle.historical_matches
            if match.confirmed_cause == entry.hypothesis_type
        ),
        default=0.0,
    )


_CANDIDATE_SCOPED_REQUIREMENTS = frozenset(
    {
        "config_diff",
        "forwarded_rate",
        "stable_raw_ingress",
        "raw_ingress",
        "source_distribution",
        "connection_pressure",
        "db_utilization",
        "pool_waits",
        "path_telemetry",
        "upstream_health",
        "dns_queries",
        "certificate_state",
    }
)


def _available_requirement(
    key: str,
    bundle: IncidentAnalysisBundle,
    candidate: HypothesisCandidate,
) -> bool:
    events = bundle.attached_events
    contains = lambda event, *values: any(
        value in (event.signal_name or "").lower()
        or value in event.event_type.lower()
        or value in json.dumps(event.raw_payload, sort_keys=True).lower()
        for value in values
    )
    rules = {
        "config_diff": lambda event: event.modality is Modality.CONFIG_CHANGE,
        "forwarded_rate": lambda event: contains(event, "forwarded_request"),
        "stable_raw_ingress": lambda event: contains(event, "raw_ingress"),
        "raw_ingress": lambda event: contains(event, "raw_ingress"),
        "source_distribution": lambda event: contains(
            event, "raw_ingress", "source_distribution", "source_ip", "client_ip"
        ),
        "connection_pressure": lambda event: contains(event, "connection_utilization"),
        "downstream_latency": lambda event: contains(event, "latency"),
        "timeout_log": lambda event: event.modality is Modality.LOG
        and contains(event, "timeout"),
        "waf_decision_logs": lambda event: contains(event, "waf_decision"),
        "waf_decisions": lambda event: contains(event, "waf_decision"),
        "db_utilization": lambda event: contains(event, "db_connection_utilization"),
        "pool_waits": lambda event: contains(event, "pool_wait", "rejected_lease"),
        "dependency_timeout": lambda event: event.modality is Modality.LOG
        and contains(event, "timeout")
        and isinstance(event.raw_payload.get("dependency_id"), str),
        "path_telemetry": lambda event: contains(
            event, "packet_loss", "retransmission", "hop_latency"
        ),
        "upstream_health": lambda event: contains(event, "upstream", "health"),
        "dns_queries": lambda event: contains(event, "dns", "resolver"),
        "certificate_state": lambda event: contains(event, "certificate", "tls"),
    }
    matcher = rules.get(key)
    if matcher is None:
        return False

    def in_scope(event: CanonicalEvent) -> bool:
        if (
            key in _CANDIDATE_SCOPED_REQUIREMENTS
            and event.entity_id != candidate.candidate_entity_id
        ):
            return False
        if key == "dependency_timeout":
            dependency_id = event.raw_payload.get("dependency_id")
            if (
                event.entity_id != candidate.candidate_entity_id
                and dependency_id != candidate.candidate_entity_id
            ):
                return False
        if key == "connection_pressure":
            return event.signal_value is not None and event.signal_value >= 0.8
        return True

    return any(matcher(event) and in_scope(event) for event in events)


def _coverage(
    entry: HypothesisDefinition,
    bundle: IncidentAnalysisBundle,
    candidate: HypothesisCandidate,
) -> EvidenceCoverage:
    expected_keys = tuple(dict.fromkeys(entry.expected_evidence))
    available = sum(
        _available_requirement(key, bundle, candidate) for key in expected_keys
    )
    return EvidenceCoverage(available=available, expected=len(expected_keys))


class RootCauseRanker:
    def __init__(self, catalogue: HypothesisCatalogue | None = None) -> None:
        self.catalogue = catalogue or load_hypothesis_catalogue()

    def score_candidate(
        self,
        candidate: HypothesisCandidate,
        bundle: IncidentAnalysisBundle,
    ) -> CandidateScore:
        entry = self.catalogue.entry(candidate.hypothesis_type)
        topology = TopologyIndex(bundle)
        topology_factor, origin, topology_path = _topology_factor(
            entry, candidate, bundle, topology
        )
        matched_conflicts = tuple(
            (pattern, source)
            for pattern in entry.conflict_patterns
            if (source := _conflict_source(pattern, bundle)) is not None
        )
        signal = _candidate_signal(entry, candidate, bundle)
        factors = {
            "symptom_compatibility": _symptom_factor(entry, self.catalogue, bundle),
            "topology_relevance": topology_factor,
            "direct_logs_alerts": _direct_log_alert_factor(
                bundle, candidate.candidate_entity_id
            ),
            "propagation_consistency": _propagation_factor(
                entry, self.catalogue, bundle
            ),
            "metric_anomaly": _metric_anomaly_factor(
                entry, candidate, bundle, topology, topology_path
            ),
            "change_causal_fit": _change_causal_fit(
                entry, candidate, bundle, topology_path, matched_conflicts
            ),
            "temporal_proximity": _temporal_factor(
                signal, _first_symptom_event(bundle)
            ),
            "historical_similarity": _historical_factor(entry, bundle),
        }
        conflicts: list[AppliedConflict] = []
        for pattern, source in matched_conflicts:
            current = factors.get(pattern.factor)
            if current is None or pattern.factor not in WEIGHTS:
                raise RankingError("conflict pattern references an unsupported factor")
            if pattern.operation == "subtract":
                updated = current - pattern.value
            elif pattern.operation == "cap":
                updated = min(current, pattern.value)
            else:  # Pydantic validates this; keep a defensive domain boundary.
                raise RankingError("conflict pattern has an unsupported operation")
            factors[pattern.factor] = max(0.0, min(1.0, updated))
            conflicts.append(
                AppliedConflict(
                    pattern_id=pattern.pattern_id,
                    factor=pattern.factor,
                    operation=pattern.operation,
                    value=pattern.value,
                    source_event_id=source.event_id,
                    statement=pattern.statement,
                )
            )
        return CandidateScore(
            candidate=candidate,
            factor_scores=factors,
            evidence_score=score_factors(factors),
            evidence_coverage=_coverage(entry, bundle, candidate),
            conflicts=tuple(conflicts),
            topology_origin=origin,
            topology_path=topology_path,
        )

    def rank(
        self,
        candidates: tuple[HypothesisCandidate, ...],
        bundle: IncidentAnalysisBundle,
    ) -> tuple[CandidateScore, ...]:
        catalogue_order = {
            entry.hypothesis_type: index
            for index, entry in enumerate(self.catalogue.hypotheses)
        }
        scored = [self.score_candidate(candidate, bundle) for candidate in candidates]
        return tuple(
            sorted(
                scored,
                key=lambda item: (
                    -item.evidence_score,
                    catalogue_order[item.candidate.hypothesis_type],
                    item.candidate.candidate_entity_id,
                ),
            )
        )


root_cause_ranker = RootCauseRanker()


__all__ = [
    "AppliedConflict",
    "CandidateScore",
    "RankingError",
    "RootCauseRanker",
    "TopologyIndex",
    "WEIGHTS",
    "WEIGHT_VALUES",
    "root_cause_ranker",
    "round_half_up",
    "score_factors",
]
