"""Pure deterministic root-cause analysis engine (blueprint §14)."""

from __future__ import annotations

from app.contracts import TopologyRelation

from .candidate_generator import (
    CandidateGenerator,
    RcaDomainError,
    TraversalPolicy,
    candidate_generator,
)
from .contracts import (
    ConflictEvidenceDraft,
    IncidentAnalysisBundle,
    RankedHypothesis,
    RcaComputationResult,
    TopologyEdgeState,
    TopologyNodeState,
    TopologyStates,
)
from .ranker import CandidateScore, RootCauseRanker, TopologyIndex, root_cause_ranker


class AnalysisEngineError(RcaDomainError):
    """Sanitized failure raised by deterministic analysis orchestration."""


class AnalysisEngine:
    """Compose candidate generation and ranking without persistence access."""

    def __init__(
        self,
        *,
        generator: CandidateGenerator = candidate_generator,
        ranker: RootCauseRanker = root_cause_ranker,
    ) -> None:
        self.generator = generator
        self.ranker = ranker

    def analyse(self, incident_bundle: IncidentAnalysisBundle) -> RcaComputationResult:
        try:
            candidates = self.generator.generate(incident_bundle)
            if not candidates:
                raise AnalysisEngineError("no catalogue-backed candidates matched")
            scored = self.ranker.rank(candidates, incident_bundle)
            ranked_hypotheses = tuple(
                RankedHypothesis(
                    hypothesis_id=f"hyp_{rank:03d}",
                    candidate_id=item.candidate.candidate_id,
                    hypothesis_type=item.candidate.hypothesis_type,
                    candidate_entity_id=item.candidate.candidate_entity_id,
                    rank=rank,
                    evidence_score=item.evidence_score,
                    evidence_coverage=item.evidence_coverage,
                    factor_scores=dict(item.factor_scores),
                    summary=self.ranker.catalogue.entry(
                        item.candidate.hypothesis_type
                    ).summary,
                )
                for rank, item in enumerate(scored, start=1)
            )
            hypothesis_ids = {
                item.candidate.candidate_id: ranked.hypothesis_id
                for item, ranked in zip(scored, ranked_hypotheses, strict=True)
            }
            conflict_evidence = tuple(
                ConflictEvidenceDraft(
                    hypothesis_id=hypothesis_ids[item.candidate.candidate_id],
                    source_event_id=conflict.source_event_id,
                    statement=conflict.statement,
                    relevance=conflict.relevance,
                    reason_code=conflict.pattern_id,
                )
                for item in scored
                for conflict in item.conflicts
            )
            typed_paths = self._typed_paths(scored, incident_bundle)
            return RcaComputationResult(
                candidates=candidates,
                ranked_hypotheses=ranked_hypotheses,
                conflict_evidence=conflict_evidence,
                conflict_reason_codes=tuple(
                    dict.fromkeys(item.reason_code for item in conflict_evidence)
                ),
                topology_states=self._topology_states(
                    ranked_hypotheses[0].candidate_entity_id, incident_bundle
                ),
                typed_paths=typed_paths,
                evidence_requirements={
                    item.hypothesis_type: tuple(
                        self.ranker.catalogue.entry(
                            item.hypothesis_type
                        ).expected_evidence
                    )
                    for item in ranked_hypotheses
                },
            )
        except RcaDomainError:
            raise
        except Exception as exc:
            raise AnalysisEngineError("deterministic RCA analysis failed") from exc

    @staticmethod
    def _typed_paths(
        scored: tuple[CandidateScore, ...],
        bundle: IncidentAnalysisBundle,
    ) -> dict[str, tuple[str, ...]]:
        topology = TopologyIndex(bundle)
        paths: dict[str, tuple[str, ...]] = {}
        configuration = next(
            (
                item
                for item in scored
                if item.candidate.hypothesis_type == "configuration_regression"
            ),
            None,
        )
        if configuration is not None:
            policy = TraversalPolicy(
                relation_type=TopologyRelation.SENDS_TRAFFIC_TO,
                direction="forward",
                max_hops=2,
            )
            choices = [
                path
                for target in bundle.incident.affected_entity_ids
                if (
                    path := topology.path(
                        configuration.candidate.candidate_entity_id,
                        target,
                        policy,
                    )
                )
                is not None
            ]
            if choices:
                paths["configuration_traffic_impact"] = max(
                    choices, key=lambda path: (len(path), path)
                )
        database = next(
            (
                item
                for item in scored
                if item.candidate.hypothesis_type
                == "database_connection_exhaustion"
            ),
            None,
        )
        if database is not None and database.topology_path:
            paths["database_dependency"] = database.topology_path
        return paths

    @staticmethod
    def _topology_states(
        suspected_root: str,
        bundle: IncidentAnalysisBundle,
    ) -> TopologyStates:
        topology = TopologyIndex(bundle)
        traffic_policy = TraversalPolicy(
            relation_type=TopologyRelation.SENDS_TRAFFIC_TO,
            direction="forward",
            max_hops=3,
        )
        reachable = topology.reachable(suspected_root, traffic_policy)
        node_states: dict[str, str] = {}
        for entity_id in bundle.incident.affected_entity_ids:
            node_states[entity_id] = "impact_path"
        if bundle.incident.primary_entity_id != suspected_root:
            node_states[bundle.incident.primary_entity_id] = "primary_affected"
        for entity_id in reachable:
            node_states.setdefault(entity_id, "blast_radius")
        node_states[suspected_root] = "suspected_root"

        impact_edges: set[tuple[str, str, str]] = set()
        for affected in bundle.incident.affected_entity_ids:
            path = topology.path(suspected_root, affected, traffic_policy)
            if path is None:
                continue
            impact_edges.update(
                (
                    source,
                    target,
                    TopologyRelation.SENDS_TRAFFIC_TO.value,
                )
                for source, target in zip(path, path[1:])
            )
        reachable_set = set(reachable)
        edge_states: list[TopologyEdgeState] = []
        for edge in bundle.topology.edges:
            identity = (edge.source, edge.target, edge.relation_type.value)
            if identity in impact_edges:
                edge_states.append(
                    TopologyEdgeState(
                        source=edge.source,
                        target=edge.target,
                        relation_type=edge.relation_type,
                        state="impact_path",
                    )
                )
            elif (
                edge.relation_type is TopologyRelation.SENDS_TRAFFIC_TO
                and edge.source in reachable_set
                and edge.target in reachable_set
            ):
                edge_states.append(
                    TopologyEdgeState(
                        source=edge.source,
                        target=edge.target,
                        relation_type=edge.relation_type,
                        state="blast_radius",
                    )
                )
        return TopologyStates(
            nodes=tuple(
                TopologyNodeState(entity_id=node.entity_id, state=node_states[node.entity_id])
                for node in bundle.topology.nodes
                if node.entity_id in node_states
            ),
            edges=tuple(edge_states),
        )


analysis_engine = AnalysisEngine()


__all__ = ["AnalysisEngine", "AnalysisEngineError", "analysis_engine"]
