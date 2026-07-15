"""
AnalysisOrchestrator — Person 1 (blueprint §5.2).

This module owns the single in-process analysis lock and the complete
sequential pipeline. No feature module calls another feature module's
internals from an API route. Only this orchestrator sequences them.

Pipeline (blueprint §5.2):
  ingest/normalize (done by ingestion layer before calling process_event)
  -> persist accepted representative
  -> evaluate detectors
  -> open or update incident
  -> create complete analysis revision
  -> atomically publish incident.current_analysis_run_id
  -> append audit records

Contract invariants enforced here:
  - Only one analysis runs at a time (threading.Lock).
  - New analysis run built without touching the current one.
  - Children (hypotheses, evidence, recs, explanation) inserted first.
  - Prior run marked superseded, incident pointer swapped — same transaction.
  - On failure: persist status=failed, leave prior run current, write
    PIPELINE_STAGE_FAILED audit entry.
  - Fingerprint match → idempotent no-op (blueprint §5.2).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import yaml
from sqlalchemy.orm import Session

from app.audit.contracts import AuditWrite
from app.audit.service import audit_service
from app.contracts import ExplanationOutput
from app.db import models
from app.db.repositories import (
    AnalysisRunRepository,
    AnomalyRepository,
    EvidenceRepository,
    HypothesisRepository,
    IncidentRepository,
)
from app.rca.contracts import TopologyStates
from app.topology.graph import get_topology_graph

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = "rca-rules-1.1"
FALLBACK_REASON_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


@dataclass(frozen=True)
class AnalysisBuildContext:
    """Immutable identity of the analysis revision currently being built."""

    analysis_run_id: str
    incident_id: str


@dataclass(frozen=True)
class ExplanationDraft:
    """A validated, run-scoped explanation awaiting atomic persistence."""

    output: ExplanationOutput
    validated: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.output, ExplanationOutput):
            raise TypeError("ExplanationDraft.output must be an ExplanationOutput")
        if not isinstance(self.validated, bool):
            raise TypeError("ExplanationDraft.validated must be a boolean")


# ---------------------------------------------------------------------------
# Protocol interfaces — feature modules implement these
# ---------------------------------------------------------------------------


@runtime_checkable
class DetectorProtocol(Protocol):
    """Implemented by app.detection (Person 3)."""

    def evaluate_event(
        self, event: models.Event, session: Session
    ) -> list[models.Anomaly]:
        """Return zero or more anomaly rows for the given event.

        The orchestrator will persist them; the detector must NOT commit."""
        ...


@runtime_checkable
class IncidentManagerProtocol(Protocol):
    """Implemented by app.incidents (Person 4)."""

    def process_anomalies(
        self,
        anomalies: list[models.Anomaly],
        trigger_event: models.Event,
        session: Session,
    ) -> models.Incident | None:
        """Open or update an incident. Returns the affected incident or None."""
        ...


@runtime_checkable
class AnalysisEngineProtocol(Protocol):
    """Implemented by Person 1's adapter around Person 4's pure RCA engine."""

    def analyse(
        self,
        incident: models.Incident,
        session: Session,
        context: AnalysisBuildContext,
    ) -> "AnalysisResult":
        """Assemble and map a complete result without committing the session."""
        ...


# ---------------------------------------------------------------------------
# AnalysisResult — typed container for the pure RCA output
# ---------------------------------------------------------------------------


class AnalysisResult:
    """Publisher-facing container returned by AnalysisEngineProtocol.analyse().

    Hypothesis, evidence, recommendation, and explanation rows are pre-built
    ORM objects (without PKs committed). Pure computation uses the separate
    ``RcaComputationResult`` boundary; the adapter creates this container.
    """

    def __init__(
        self,
        hypotheses: list[models.Hypothesis],
        evidence_rows: list[models.Evidence],
        recommendation_rows: list[models.PlaybookRecommendation],
        explanation_payload: dict[str, Any] | None = None,
        *,
        explanation_rows: list[ExplanationDraft] | None = None,
        explanation_fallback_reason: str | None = None,
        explanation_fallback_attempt_count: int = 0,
        topology_states: TopologyStates | None = None,
        conflict_reason_codes: tuple[str, ...] = (),
        evidence_requirements: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        if explanation_payload is not None and explanation_rows is not None:
            raise ValueError(
                "provide explanation_rows or deprecated explanation_payload, not both"
            )
        self.hypotheses = hypotheses
        self.evidence_rows = evidence_rows
        self.recommendation_rows = recommendation_rows
        if explanation_rows is not None:
            self.explanation_rows = list(explanation_rows)
        elif explanation_payload is not None:
            self.explanation_rows = [
                ExplanationDraft(
                    output=ExplanationOutput.model_validate(explanation_payload)
                )
            ]
        else:
            self.explanation_rows = []
        self.explanation_payload = explanation_payload
        self.explanation_fallback_reason = explanation_fallback_reason
        self.explanation_fallback_attempt_count = explanation_fallback_attempt_count
        self.topology_states = topology_states or TopologyStates()
        self.conflict_reason_codes = tuple(conflict_reason_codes)
        self.evidence_requirements = MappingProxyType(
            {
                key: tuple(requirements)
                for key, requirements in (evidence_requirements or {}).items()
            }
        )
        self._validate_fallback_metadata()

    def _validate_fallback_metadata(self) -> None:
        reason = self.explanation_fallback_reason
        attempts = self.explanation_fallback_attempt_count
        if isinstance(attempts, bool) or not isinstance(attempts, int):
            raise TypeError("explanation fallback attempt count must be an integer")
        if reason is None:
            if attempts != 0:
                raise ValueError(
                    "fallback attempt count must be zero when no fallback occurred"
                )
            return
        if not FALLBACK_REASON_PATTERN.fullmatch(reason):
            raise ValueError(
                "explanation fallback reason must be an uppercase reason code"
            )
        if attempts < 1:
            raise ValueError(
                "fallback attempt count must be positive when fallback occurred"
            )


# ---------------------------------------------------------------------------
# AnalysisOrchestrator
# ---------------------------------------------------------------------------


class AnalysisOrchestrator:
    """Single in-process analysis coordinator (blueprint §5.2).

    Usage::

        orchestrator = AnalysisOrchestrator()
        orchestrator.register_detector(my_detector)
        orchestrator.register_incident_manager(my_manager)
        orchestrator.register_analysis_engine(my_engine)

        # Called after an accepted event is persisted:
        orchestrator.process_event(event, session)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._detector: DetectorProtocol | None = None
        self._incident_manager: IncidentManagerProtocol | None = None
        self._analysis_engine: AnalysisEngineProtocol | None = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_detector(self, detector: DetectorProtocol) -> None:
        self._detector = detector

    def register_incident_manager(self, manager: IncidentManagerProtocol) -> None:
        self._incident_manager = manager

    def register_analysis_engine(self, engine: AnalysisEngineProtocol) -> None:
        self._analysis_engine = engine

    # ------------------------------------------------------------------
    # Public API — called by ingestion layer
    # ------------------------------------------------------------------

    def process_event(self, event: models.Event, session: Session) -> None:
        """Process one accepted event through the full analysis pipeline.

        Acquires the global analysis lock. The caller (ingestion route)
        must NOT commit the session — the orchestrator commits atomically.
        """
        with self._lock:
            self._run_pipeline(event, session)

    def recompute(self, incident_id: str, session: Session) -> None:
        """Trigger a forced re-analysis for an existing incident.

        Used by POST /incidents/{id}/recompute. Idempotent if the
        fingerprint has not changed.
        """
        with self._lock:
            incident_repo = IncidentRepository(session)
            incident = incident_repo.get_by_id(incident_id)
            if incident is None:
                raise ValueError(f"Incident not found: {incident_id}")
            self._run_rca_and_publish(incident, trigger_event=None, session=session)

    # ------------------------------------------------------------------
    # Pipeline stages (private)
    # ------------------------------------------------------------------

    def _run_pipeline(self, event: models.Event, session: Session) -> None:
        """Full pipeline: detect → incident → RCA → publish → audit."""
        incident_id: str | None = None
        run_id: str | None = None
        stage = "detection"
        try:
            # Stage 1 — Detection
            anomalies = self._stage_detect(event, session)

            # Stage 2 — Incident management
            stage = "incident_management"
            incident = self._stage_incident(anomalies, event, session)

            if incident is None:
                # Normal baseline event; no incident affected — no revision needed
                return

            incident_id = incident.id

            # Stage 3 — RCA + atomic publication
            stage = "rca_publication"
            run_id = self._run_rca_and_publish(incident, trigger_event=event, session=session)

        except Exception as exc:
            logger.exception("Pipeline stage '%s' failed for event %s", stage, event.id)
            if incident_id and run_id:
                self._persist_failed_run(
                    run_id=run_id,
                    incident_id=incident_id,
                    reason=f"{stage}: {type(exc).__name__}: {exc}",
                    session=session,
                )
            raise

    def _stage_detect(
        self, event: models.Event, session: Session
    ) -> list[models.Anomaly]:
        """Call the detector and persist resulting anomaly rows."""
        anomaly_repo = AnomalyRepository(session)

        if self._detector is None:
            return []

        anomalies = self._detector.evaluate_event(event, session)
        for anomaly in anomalies:
            anomaly_repo.persist(anomaly)
            audit_service.append(
                AuditWrite(
                    action="ANOMALY_DETECTED",
                    actor_type="system",
                    actor_id="detector",
                    object_type="anomaly",
                    object_id=anomaly.id,
                    request_id=f"pipeline:{event.id}",
                    reason_codes=[anomaly.detector_id],
                    metadata={
                        "event_id": event.id,
                        "detector_id": anomaly.detector_id,
                        "score": anomaly.score,
                        "context_only": anomaly.context_only,
                    },
                ),
                session,
            )
        return anomalies

    def _stage_incident(
        self,
        anomalies: list[models.Anomaly],
        trigger_event: models.Event,
        session: Session,
    ) -> models.Incident | None:
        """Call the incident manager."""
        if self._incident_manager is None:
            return None

        incident = self._incident_manager.process_anomalies(
            anomalies, trigger_event, session
        )
        return incident

    def _run_rca_and_publish(
        self,
        incident: models.Incident,
        trigger_event: models.Event | None,
        session: Session,
    ) -> str:
        """Run RCA and atomically publish the new analysis run.

        Returns the new run_id.
        """
        run_repo = AnalysisRunRepository(session)
        incident_repo = IncidentRepository(session)

        # Build fingerprint
        attached = incident_repo.get_attached_events(incident.id)
        event_ids = sorted(ev.event_id for ev in attached)
        fingerprint = self.compute_fingerprint(
            incident_event_ids=event_ids,
            session=session,
        )

        # Idempotency: skip if fingerprint unchanged
        if run_repo.fingerprint_exists_as_current(incident.id, fingerprint):
            logger.debug(
                "Incident %s fingerprint unchanged — skipping recompute", incident.id
            )
            return incident.current_analysis_run_id or ""  # type: ignore[return-value]

        # Determine next revision
        next_rev = run_repo.get_next_revision(incident.id)
        new_run_id = f"run_{uuid.uuid4().hex[:12]}"

        # Create the new run in 'building' status
        new_run = models.AnalysisRun(
            id=new_run_id,
            incident_id=incident.id,
            revision=next_rev,
            status="building",
            trigger_event_id=trigger_event.id if trigger_event else None,
            input_fingerprint=fingerprint,
            algorithm_version=ALGORITHM_VERSION,
            created_at=datetime.now(tz=timezone.utc),
            completed_at=None,
            failure_reason=None,
        )
        run_repo.create(new_run)

        context = AnalysisBuildContext(
            analysis_run_id=new_run.id,
            incident_id=incident.id,
        )
        try:
            # A savepoint keeps the building run outside the publication unit.
            # Any invalid child output rolls back without disturbing the prior
            # current run; the building row can then be marked failed.
            with session.begin_nested():
                analysis_result: AnalysisResult | None = None
                if self._analysis_engine is not None:
                    analysis_result = self._analysis_engine.analyse(
                        incident, session, context
                    )

                # Atomically publish: insert children → supersede prior → swap pointer
                self._atomic_publish(
                    new_run=new_run,
                    analysis_result=analysis_result,
                    incident=incident,
                    session=session,
                    run_repo=run_repo,
                    incident_repo=incident_repo,
                )
        except Exception as exc:
            self._persist_failed_run(
                run_id=new_run.id,
                incident_id=incident.id,
                reason=f"rca_publication: {type(exc).__name__}: {exc}",
                session=session,
            )
            raise

        return new_run_id

    def _atomic_publish(
        self,
        new_run: models.AnalysisRun,
        analysis_result: AnalysisResult | None,
        incident: models.Incident,
        session: Session,
        run_repo: AnalysisRunRepository,
        incident_repo: IncidentRepository,
    ) -> None:
        """Insert all children, mark prior superseded, swap current pointer.

        Blueprint §5.2: build a new run without changing the current one; after
        all outputs validate, mark the previous run superseded and atomically
        point the incident to the new current run.
        """
        hyp_repo = HypothesisRepository(session)
        ev_repo = EvidenceRepository(session)

        top_hypothesis_id: str | None = None

        if analysis_result is not None:
            self._validate_analysis_result(new_run, incident, analysis_result)
            self._validate_explanation_rows(new_run, incident, analysis_result)

            # Insert hypotheses
            for hyp in analysis_result.hypotheses:
                hyp.analysis_run_id = new_run.id
                hyp.incident_id = incident.id
                hyp_repo.persist(hyp)

            # Insert evidence
            for ev in analysis_result.evidence_rows:
                ev.analysis_run_id = new_run.id
                ev.incident_id = incident.id
                ev_repo.persist(ev)

            # Insert recommendations
            for rec in analysis_result.recommendation_rows:
                rec.analysis_run_id = new_run.id
                rec.incident_id = incident.id
                session.add(rec)

            # Append every validated explanation; never replace earlier rows.
            for draft in analysis_result.explanation_rows:
                output = draft.output
                explanation = models.Explanation(
                    id=f"exp_{uuid.uuid4().hex[:12]}",
                    analysis_run_id=new_run.id,
                    incident_id=incident.id,
                    generator=output.generator,
                    validated=draft.validated,
                    payload=output.model_dump(mode="json"),
                    created_at=datetime.now(tz=timezone.utc),
                )
                session.add(explanation)

            if analysis_result.explanation_fallback_reason is not None:
                audit_service.append(
                    AuditWrite(
                        action="EXPLANATION_FALLBACK_USED",
                        actor_type="system",
                        actor_id="explanation_service",
                        object_type="incident",
                        object_id=incident.id,
                        incident_id=incident.id,
                        analysis_run_id=new_run.id,
                        analysis_revision=new_run.revision,
                        request_id=f"analysis:{new_run.id}",
                        reason_codes=[analysis_result.explanation_fallback_reason],
                        metadata={
                            "reason_code": analysis_result.explanation_fallback_reason,
                            "attempt_count": (
                                analysis_result.explanation_fallback_attempt_count
                            ),
                        },
                    ),
                    session,
                )

            session.flush()

            # Top hypothesis
            if analysis_result.hypotheses:
                ranked = sorted(analysis_result.hypotheses, key=lambda h: h.rank)
                top_hypothesis_id = ranked[0].id

        # Supersede the prior current run (if any)
        prior_run_id = incident.current_analysis_run_id
        if prior_run_id:
            run_repo.supersede(prior_run_id)

        # Mark new run current
        run_repo.mark_current(new_run.id)

        # Swap the incident pointer (one atomic flush)
        incident_repo.set_current_analysis_run(
            incident.id,
            new_run.id,
            top_hypothesis_id=top_hypothesis_id,
        )

        # Audit
        audit_service.append(
            AuditWrite(
                action="ANALYSIS_PUBLISHED",
                actor_type="system",
                actor_id="orchestrator",
                object_type="incident",
                object_id=incident.id,
                incident_id=incident.id,
                analysis_run_id=new_run.id,
                analysis_revision=new_run.revision,
                request_id=f"analysis:{new_run.id}",
                metadata={
                    "revision": new_run.revision,
                    "fingerprint": new_run.input_fingerprint,
                    "prior_run_id": prior_run_id,
                    "algorithm_version": ALGORITHM_VERSION,
                },
            ),
            session,
        )

    @staticmethod
    def _validate_analysis_result(
        new_run: models.AnalysisRun,
        incident: models.Incident,
        analysis_result: AnalysisResult,
    ) -> None:
        """Reject cross-run, dangling, or non-catalogue publisher input."""

        hypotheses = analysis_result.hypotheses
        hypothesis_ids = {item.id for item in hypotheses}
        if len(hypothesis_ids) != len(hypotheses):
            raise ValueError("analysis result hypothesis IDs must be unique")
        ranks = sorted(item.rank for item in hypotheses)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("analysis result ranks must be unique and consecutive")
        for hypothesis in hypotheses:
            if hypothesis.analysis_run_id != new_run.id:
                raise ValueError("hypothesis analysis_run_id does not match pending run")
            if hypothesis.incident_id != incident.id:
                raise ValueError("hypothesis incident_id does not match pending incident")

        conflicting_codes: set[str] = set()
        for evidence in analysis_result.evidence_rows:
            if evidence.analysis_run_id != new_run.id:
                raise ValueError("evidence analysis_run_id does not match pending run")
            if evidence.incident_id != incident.id:
                raise ValueError("evidence incident_id does not match pending incident")
            if evidence.hypothesis_id not in hypothesis_ids:
                raise ValueError("evidence references an unknown pending hypothesis")
            if evidence.kind == "conflicting":
                conflicting_codes.add(evidence.reason_code)

        for recommendation in analysis_result.recommendation_rows:
            if recommendation.analysis_run_id != new_run.id:
                raise ValueError(
                    "recommendation analysis_run_id does not match pending run"
                )
            if recommendation.incident_id != incident.id:
                raise ValueError(
                    "recommendation incident_id does not match pending incident"
                )
            if recommendation.hypothesis_id not in hypothesis_ids:
                raise ValueError(
                    "recommendation references an unknown pending hypothesis"
                )

        declared_conflicts = set(analysis_result.conflict_reason_codes)
        known_conflicts = AnalysisOrchestrator._catalogue_conflict_reason_codes()
        if not declared_conflicts.issubset(known_conflicts):
            raise ValueError("analysis result contains a non-catalogue conflict code")
        if not declared_conflicts.issubset(conflicting_codes):
            raise ValueError("declared conflict code has no conflicting evidence row")

        valid_requirement_keys = hypothesis_ids | {item.type for item in hypotheses}
        if not set(analysis_result.evidence_requirements).issubset(
            valid_requirement_keys
        ):
            raise ValueError("evidence requirements reference an unknown hypothesis")
        if any(
            len(requirements) != len(set(requirements))
            for requirements in analysis_result.evidence_requirements.values()
        ):
            raise ValueError("evidence requirements must be unique per hypothesis")

        topology = get_topology_graph()
        node_ids = set(topology.graph.nodes)
        seen_nodes: set[str] = set()
        for state in analysis_result.topology_states.nodes:
            if state.entity_id not in node_ids:
                raise ValueError("topology state references an unknown entity")
            if state.entity_id in seen_nodes:
                raise ValueError("topology node state is duplicated")
            seen_nodes.add(state.entity_id)
        edge_ids = {
            (row["source"], row["target"], row["relation_type"])
            for row in topology.edge_records
        }
        seen_edges: set[tuple[str, str, str]] = set()
        for state in analysis_result.topology_states.edges:
            identity = (state.source, state.target, state.relation_type.value)
            if identity not in edge_ids:
                raise ValueError("topology state references an unknown typed edge")
            if identity in seen_edges:
                raise ValueError("topology edge state is duplicated")
            seen_edges.add(identity)

    @staticmethod
    @lru_cache(maxsize=1)
    def _catalogue_conflict_reason_codes() -> set[str]:
        path = Path(__file__).resolve().parents[1] / "fixtures" / "hypotheses.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return {
            str(pattern["pattern_id"])
            for hypothesis in payload.get("hypotheses", [])
            for pattern in hypothesis.get("conflict_patterns", [])
            if isinstance(pattern, dict) and pattern.get("pattern_id")
        }

    @staticmethod
    def _validate_explanation_rows(
        new_run: models.AnalysisRun,
        incident: models.Incident,
        analysis_result: AnalysisResult,
    ) -> None:
        rows = analysis_result.explanation_rows
        if not rows:
            raise ValueError("analysis result must include a template explanation")
        hypothesis_ids = {item.id for item in analysis_result.hypotheses}
        identities: set[tuple[str, str]] = set()
        has_template = False
        for draft in rows:
            if not draft.validated:
                raise ValueError("unvalidated explanation drafts cannot be published")
            output = draft.output
            if output.analysis_run_id != new_run.id:
                raise ValueError("explanation analysis_run_id does not match pending run")
            if output.incident_id != incident.id:
                raise ValueError("explanation incident_id does not match pending incident")
            if output.hypothesis_id not in hypothesis_ids:
                raise ValueError(
                    "explanation hypothesis_id is not part of the pending run"
                )
            identity = (output.generator, output.hypothesis_id)
            if identity in identities:
                raise ValueError(
                    "duplicate explanation generator for the same hypothesis"
                )
            identities.add(identity)
            has_template = has_template or output.generator == "template"
        if not has_template:
            raise ValueError("analysis result must retain a template explanation")

    def _persist_failed_run(
        self,
        run_id: str,
        incident_id: str,
        reason: str,
        session: Session,
    ) -> None:
        """Mark a building run as failed. Leave prior run current. Write audit."""
        run_repo = AnalysisRunRepository(session)
        try:
            run_repo.mark_failed(run_id, reason)
            failed_run = run_repo.get_by_id(run_id)
            audit_service.append(
                AuditWrite(
                    action="PIPELINE_STAGE_FAILED",
                    actor_type="system",
                    actor_id="orchestrator",
                    object_type="incident",
                    object_id=incident_id,
                    incident_id=incident_id,
                    analysis_run_id=run_id,
                    analysis_revision=failed_run.revision if failed_run else None,
                    request_id=f"analysis:{run_id}",
                    reason_codes=["PIPELINE_STAGE_FAILED"],
                    metadata={
                        "failed_run_id": run_id,
                        "sanitized_reason": reason[:500],
                    },
                ),
                session,
            )
            session.flush()
        except Exception:
            logger.exception(
                "Failed to persist failed-run record for run %s / incident %s",
                run_id,
                incident_id,
            )

    # ------------------------------------------------------------------
    # Fingerprint computation (blueprint §5.2)
    # ------------------------------------------------------------------

    def compute_fingerprint(
        self,
        incident_event_ids: list[str],
        session: Session,
    ) -> str:
        """SHA-256(sorted event IDs + hashes | topology fixture version | catalogue versions | algorithm version).

        Blueprint §5.2: identical input always produces identical fingerprint.
        """
        from app.config import settings
        from app.db.repositories.event_repository import EventRepository

        sorted_ids = sorted(incident_event_ids)

        # Get event content hashes from database
        event_repo = EventRepository(session)
        db_events = event_repo.get_events_by_ids(sorted_ids)
        event_map = {ev.id: ev for ev in db_events}

        event_hashes: dict[str, str] = {}
        for ev_id in sorted_ids:
            ev = event_map.get(ev_id)
            if ev is None:
                event_hashes[ev_id] = "missing"
                continue

            # Deterministic hash of event content
            h = hashlib.sha256()
            h.update(ev.id.encode("utf-8"))
            h.update(str(ev.timestamp.timestamp()).encode("utf-8"))
            h.update(ev.entity_id.encode("utf-8"))
            h.update(ev.modality.encode("utf-8"))
            h.update(ev.event_type.encode("utf-8"))
            h.update(str(ev.severity).encode("utf-8"))
            if ev.signal_name:
                h.update(ev.signal_name.encode("utf-8"))
            if ev.signal_value is not None:
                h.update(str(ev.signal_value).encode("utf-8"))
            if ev.unit:
                h.update(ev.unit.encode("utf-8"))
            if ev.trace_or_session_id:
                h.update(ev.trace_or_session_id.encode("utf-8"))
            if ev.raw_payload:
                h.update(json.dumps(ev.raw_payload, sort_keys=True).encode("utf-8"))
            event_hashes[ev_id] = h.hexdigest()

        # Topology fixture version
        try:
            from pathlib import Path
            topo_path = Path(__file__).resolve().parents[1] / "fixtures" / "topology.json"
            topo = json.loads(topo_path.read_text(encoding="utf-8"))
            topology_version = topo.get("version", "unknown")
        except Exception:
            topology_version = "unknown"

        # Catalogue versions (hypotheses, symptom_families, detector_rules, playbooks)
        catalogue_versions: dict[str, str] = {}
        for name in ("hypotheses.yaml", "symptom_families.yaml", "detector_rules.yaml", "playbooks.yaml"):
            try:
                import yaml
                from pathlib import Path
                path = Path(__file__).resolve().parents[1] / "fixtures" / name
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                catalogue_versions[name] = str(data.get("version", "unknown"))
            except Exception:
                catalogue_versions[name] = "unknown"

        fingerprint_input = json.dumps(
            {
                "event_ids": sorted_ids,
                "event_hashes": event_hashes,
                "topology_version": topology_version,
                "catalogue_versions": catalogue_versions,
                "algorithm_version": ALGORITHM_VERSION,
            },
            sort_keys=True,
        ).encode("utf-8")

        digest = hashlib.sha256(fingerprint_input).hexdigest()
        return f"sha256:{digest}"

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "detector_registered": self._detector is not None,
            "incident_manager_registered": self._incident_manager is not None,
            "analysis_engine_registered": self._analysis_engine is not None,
            "algorithm_version": ALGORITHM_VERSION,
        }


# ---------------------------------------------------------------------------
# Module-level singleton — imported by main.py and ingestion layer
# ---------------------------------------------------------------------------

orchestrator = AnalysisOrchestrator()
