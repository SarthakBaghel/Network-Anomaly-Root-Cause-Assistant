"""Database-aware adapter around the database-free Person 4 RCA engine."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.explanation.service import ExplanationService

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    AnalysisRun,
    AnalysisRunStatus,
    EvidenceItem,
    Hypothesis,
)
from app.db import models
from app.evidence.collector import calculate_evidence_coverage, collect_evidence
from app.playbooks.engine import get_recommendations
from app.rca.contracts import IncidentAnalysisBundle, RcaComputationResult

from .analysis_bundle import build_incident_analysis_bundle
from .orchestrator import AnalysisBuildContext, AnalysisResult


CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "hypotheses.yaml"


class PureRcaEngine(Protocol):
    """The only interface Person 4's deterministic engine must implement."""

    def analyse(self, incident_bundle: IncidentAnalysisBundle) -> RcaComputationResult: ...


class RcaAdapterError(RuntimeError):
    """Sanitized adapter-domain failure safe for failed-run persistence."""


@lru_cache(maxsize=1)
def _catalogue() -> dict[str, dict]:
    payload = yaml.safe_load(CATALOGUE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("hypotheses"), list):
        raise RcaAdapterError("hypothesis catalogue is invalid")
    return {
        str(row["hypothesis_type"]): row
        for row in payload["hypotheses"]
        if isinstance(row, dict) and row.get("hypothesis_type")
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _persistent_id(prefix: str, local_id: str, run_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}|{local_id}".encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


class RcaAnalysisAdapter:
    """Load DB state, call the pure engine, then prepare uncommitted rows."""

    def __init__(
        self,
        engine: PureRcaEngine,
        *,
        bundle_builder: Callable[..., IncidentAnalysisBundle] = build_incident_analysis_bundle,
        explanations: "ExplanationService | None" = None,
    ) -> None:
        # Deferred import to avoid the orchestration.__init__ → rca_adapter →
        # explanation.service → orchestration.orchestrator circular load.
        if explanations is None:
            from app.explanation.service import explanation_service
            explanations = explanation_service
        self.engine = engine
        self.bundle_builder = bundle_builder
        self.explanations = explanations

    def analyse(
        self,
        incident: models.Incident,
        session: Session,
        context: AnalysisBuildContext,
    ) -> AnalysisResult:
        run_row = session.get(models.AnalysisRun, context.analysis_run_id)
        if run_row is None or run_row.incident_id != context.incident_id:
            raise RcaAdapterError("pending analysis run does not resolve")
        try:
            bundle = self.bundle_builder(
                incident.id,
                session,
                input_fingerprint=run_row.input_fingerprint,
            )
        except Exception as exc:
            raise RcaAdapterError("incident analysis bundle could not be assembled") from exc
        try:
            computed = self.engine.analyse(bundle)
        except Exception as exc:
            raise RcaAdapterError("pure RCA computation failed") from exc
        try:
            return self._to_publication_result(
                computed,
                bundle=bundle,
                run_row=run_row,
                context=context,
                session=session,
            )
        except RcaAdapterError:
            raise
        except Exception as exc:
            raise RcaAdapterError("RCA result could not be mapped for publication") from exc

    def _to_publication_result(
        self,
        computed: RcaComputationResult,
        *,
        bundle: IncidentAnalysisBundle,
        run_row: models.AnalysisRun,
        context: AnalysisBuildContext,
        session: Session,
    ) -> AnalysisResult:
        if not computed.ranked_hypotheses:
            raise RcaAdapterError("pure RCA computation returned no hypotheses")

        entity_types = {
            node.entity_id: node.entity_type for node in bundle.topology.nodes
        }
        persistent_ids = {
            ranked.hypothesis_id: _persistent_id(
                "hyp", ranked.hypothesis_id, context.analysis_run_id
            )
            for ranked in computed.ranked_hypotheses
        }
        hypotheses: list[models.Hypothesis] = []
        evidence_rows: list[models.Evidence] = []
        recommendation_rows: list[models.PlaybookRecommendation] = []
        contract_hypotheses: dict[str, Hypothesis] = {}
        contract_evidence: dict[str, list[EvidenceItem]] = {}
        playbooks_by_hypothesis: dict[str, list] = {}

        for ranked in sorted(computed.ranked_hypotheses, key=lambda item: item.rank):
            persistent_id = persistent_ids[ranked.hypothesis_id]
            hypothesis = Hypothesis(
                hypothesis_id=persistent_id,
                analysis_run_id=context.analysis_run_id,
                incident_id=context.incident_id,
                hypothesis_type=ranked.hypothesis_type,
                candidate_entity_id=ranked.candidate_entity_id,
                rank=ranked.rank,
                evidence_score=ranked.evidence_score,
                evidence_coverage=ranked.evidence_coverage,
                factor_scores=dict(ranked.factor_scores),
                summary=ranked.summary,
            )
            contract_hypotheses[ranked.hypothesis_id] = hypothesis

            entry = deepcopy(_catalogue().get(ranked.hypothesis_type))
            if entry is None:
                raise RcaAdapterError("computed hypothesis is not catalogue-backed")
            conflicts = [
                item
                for item in computed.conflict_evidence
                if item.hypothesis_id == ranked.hypothesis_id
            ]
            if conflicts:
                entry["applied_conflict_effects"] = [
                    {
                        "reason_code": item.reason_code,
                        "source_event_id": item.source_event_id,
                        "statement": item.statement,
                    }
                    for item in conflicts
                ]
            evidence = collect_evidence(
                hypothesis,
                list(bundle.attached_events),
                entry,
                [],
            )
            collected_coverage = calculate_evidence_coverage(entry, evidence)
            if collected_coverage != ranked.evidence_coverage:
                raise RcaAdapterError(
                    "computed evidence coverage does not match collected evidence "
                    f"for {ranked.hypothesis_type}: computed="
                    f"{ranked.evidence_coverage.available}/{ranked.evidence_coverage.expected}, "
                    f"collected={collected_coverage.available}/{collected_coverage.expected}"
                )
            contract_evidence[ranked.hypothesis_id] = evidence

            hypotheses.append(
                models.Hypothesis(
                    id=persistent_id,
                    analysis_run_id=context.analysis_run_id,
                    incident_id=context.incident_id,
                    type=ranked.hypothesis_type,
                    candidate_entity_id=ranked.candidate_entity_id,
                    rank=ranked.rank,
                    evidence_score=ranked.evidence_score,
                    coverage=ranked.evidence_coverage.model_dump(mode="json"),
                    factor_scores=dict(ranked.factor_scores),
                    summary=ranked.summary,
                )
            )
            evidence_rows.extend(
                models.Evidence(
                    id=item.evidence_id,
                    analysis_run_id=context.analysis_run_id,
                    incident_id=context.incident_id,
                    hypothesis_id=persistent_id,
                    kind=item.kind.value,
                    source_event_id=item.source_event_id,
                    statement=item.statement,
                    relevance=item.relevance,
                    reason_code=item.reason_code,
                    created_at=item.created_at,
                )
                for item in evidence
            )

            entity_type = entity_types.get(ranked.candidate_entity_id)
            if entity_type is None:
                raise RcaAdapterError("computed candidate entity does not resolve in topology")
            applicable = {
                step.step_id: step
                for step in get_recommendations(ranked.hypothesis_type, entity_type)
            }
            declared_step_ids = [
                *entry.get("diagnostic_step_ids", []),
                *entry.get("remediation_step_ids", []),
            ]
            missing_step_ids = [
                step_id for step_id in declared_step_ids if step_id not in applicable
            ]
            if missing_step_ids:
                raise RcaAdapterError(
                    "hypothesis references a missing or incompatible playbook step"
                )
            playbooks = [applicable[step_id] for step_id in declared_step_ids]
            playbooks_by_hypothesis[ranked.hypothesis_id] = playbooks
            recommendation_rows.extend(
                models.PlaybookRecommendation(
                    id=_persistent_id(
                        "rec",
                        f"{ranked.hypothesis_id}|{step.step_id}",
                        context.analysis_run_id,
                    ),
                    analysis_run_id=context.analysis_run_id,
                    incident_id=context.incident_id,
                    hypothesis_id=persistent_id,
                    step_id=step.step_id,
                    state="proposed",
                    rationale=f"Catalogue-backed step for {ranked.hypothesis_type}.",
                    presentation={
                        "title": step.title,
                        "step_type": step.step_type,
                        "risk_level": step.risk_level,
                        "requires_human_approval": step.requires_human_approval,
                        "instructions": "\n".join(step.instructions),
                        "catalogue_order": catalogue_order,
                    },
                )
                for catalogue_order, step in enumerate(playbooks)
            )

        top = min(computed.ranked_hypotheses, key=lambda item: item.rank)
        run = AnalysisRun(
            analysis_run_id=context.analysis_run_id,
            incident_id=context.incident_id,
            revision=run_row.revision,
            status=AnalysisRunStatus.BUILDING,
            trigger_event_id=run_row.trigger_event_id,
            input_fingerprint=run_row.input_fingerprint,
            created_at=_utc(run_row.created_at),
            completed_at=None,
            algorithm_version=run_row.algorithm_version,
        )

        def active_build_run_id(incident_id: str) -> str | None:
            """Resolve the still-active pending publication after LLM latency.

            The new run intentionally remains ``building`` until every child
            output has validated and the atomic publisher swaps the incident's
            current pointer. Treating only an already-current row as valid here
            makes every production LLM result stale by construction.
            """

            return session.scalar(
                select(models.AnalysisRun.id).where(
                    models.AnalysisRun.id == context.analysis_run_id,
                    models.AnalysisRun.incident_id == incident_id,
                    models.AnalysisRun.status == "building",
                )
            )

        explanation_result = self.explanations.generate(
            run,
            contract_hypotheses[top.hypothesis_id],
            contract_evidence[top.hypothesis_id],
            playbooks_by_hypothesis[top.hypothesis_id],
            candidate_entity_type=entity_types[top.candidate_entity_id],
            current_run_id_provider=active_build_run_id,
        )
        node_states = {
            item.entity_id: item.state for item in computed.topology_states.nodes
        }
        edge_states = {
            (item.source, item.target, item.relation_type.value): item.state
            for item in computed.topology_states.edges
        }
        topology_snapshot = {
            "fixture_version": bundle.topology.fixture_version,
            "nodes": [
                {
                    "id": node.entity_id,
                    "name": node.name,
                    "type": node.entity_type,
                    "service": node.service,
                    "criticality": node.criticality,
                    "state": node_states.get(node.entity_id),
                }
                for node in bundle.topology.nodes
            ],
            "edges": [
                {
                    "source": edge.source,
                    "target": edge.target,
                    "relation_type": edge.relation_type.value,
                    "relationship": edge.relationship,
                    "state": edge_states.get(
                        (edge.source, edge.target, edge.relation_type.value)
                    ),
                }
                for edge in bundle.topology.edges
            ],
        }
        return AnalysisResult(
            hypotheses=hypotheses,
            evidence_rows=evidence_rows,
            recommendation_rows=recommendation_rows,
            topology_states=computed.topology_states,
            typed_paths=computed.typed_paths,
            conflict_reason_codes=computed.conflict_reason_codes,
            evidence_requirements=computed.evidence_requirements,
            topology_snapshot=topology_snapshot,
            **explanation_result.as_analysis_result_kwargs(),
        )


__all__ = ["PureRcaEngine", "RcaAdapterError", "RcaAnalysisAdapter"]
