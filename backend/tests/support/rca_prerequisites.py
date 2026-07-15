from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.contracts import AnomalyRecord, CanonicalEvent, EvidenceCoverage
from app.db import models
from app.rca import (
    ConflictEvidenceDraft,
    HypothesisCandidate,
    RankedHypothesis,
    RcaComputationResult,
    TopologyNodeState,
    TopologyStates,
)
from app.topology.graph import get_topology_graph


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _event_row(item: CanonicalEvent) -> models.Event:
    return models.Event(
        id=item.event_id,
        timestamp=item.timestamp,
        ingested_at=item.ingested_at,
        entity_id=item.entity_id,
        modality=item.modality.value,
        event_type=item.event_type,
        severity=item.severity,
        signal_name=item.signal_name,
        signal_value=item.signal_value,
        unit=item.unit,
        trace_or_session_id=item.trace_or_session_id,
        source=item.source,
        source_record_id=item.source_record_id,
        schema_version=item.schema_version,
        quality_flags=item.quality_flags,
        raw_payload=item.raw_payload,
        status="accepted",
    )


def _anomaly_row(item: AnomalyRecord) -> models.Anomaly:
    return models.Anomaly(
        id=item.anomaly_id,
        event_id=item.event_id,
        detector_id=item.detector_id,
        type=item.anomaly_type,
        detected_at=item.detected_at,
        score=item.score,
        threshold=item.threshold,
        context_only=item.context_only,
        can_open_incident=item.can_open_incident,
        window_start=item.window_start,
        window_end=item.window_end,
        features=item.features,
        explanation=item.explanation,
    )


def seed_golden_incident(session: Session) -> models.Incident:
    topology = get_topology_graph()
    for node in topology.node_records:
        session.add(
            models.Entity(
                id=node["id"],
                name=node["name"],
                entity_type=node["entity_type"],
                service=node["service"],
                criticality=node["criticality"],
                metadata_json=node.get("metadata", {}),
            )
        )
    events = [
        CanonicalEvent.model_validate_json(line)
        for line in (FIXTURES / "golden_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    session.add_all(_event_row(item) for item in events)

    anomaly_payload = json.loads(
        (FIXTURES / "golden_anomalies.json").read_text(encoding="utf-8")
    )
    session.add_all(
        _anomaly_row(AnomalyRecord.model_validate(item))
        for item in anomaly_payload["anomalies"]
        + anomaly_payload["context_markers"]
    )

    frozen = json.loads(
        (FIXTURES / "golden_incident_bundle.json").read_text(encoding="utf-8")
    )
    source = frozen["incident"]
    incident = models.Incident(
        id=source["incident_id"],
        title=source["title"],
        status="open",
        severity=source["severity"],
        started_at=datetime.fromisoformat(source["started_at"].replace("Z", "+00:00")),
        last_event_at=datetime.fromisoformat(
            source["last_event_at"].replace("Z", "+00:00")
        ),
        primary_entity_id=source["primary_entity_id"],
        affected_entity_ids=source["affected_entity_ids"],
        anomaly_count=source["anomaly_count"],
        current_analysis_run_id=None,
        top_hypothesis_id=None,
        confirmed_hypothesis_id=None,
    )
    session.add(incident)
    for evaluation in frozen["attached_events"] + frozen["excluded_events"]:
        session.add(
            models.IncidentEventEvaluation(
                incident_id=incident.id,
                event_id=evaluation["event_id"],
                decision=evaluation["decision"],
                attachment_score=evaluation["attachment_score"],
                attachment_reasons=evaluation["attachment_reasons"],
            )
        )
        if evaluation["decision"] == "attached":
            session.add(
                models.IncidentEvent(
                    incident_id=incident.id,
                    event_id=evaluation["event_id"],
                    attachment_score=evaluation["attachment_score"],
                    attachment_reasons=evaluation["attachment_reasons"],
                )
            )
    session.add(
        models.HistoricalIncident(
            id="hist_gateway_rate_limit_001",
            fingerprint="gateway-rate-limit-half-feature-match",
            confirmed_cause="configuration_regression",
            summary="Prior confirmed gateway rate-limit regression.",
            feature_vector={
                "entity_type": "gateway",
                "change_type": "rate_limit.enabled",
                "forwarded_traffic_spike": True,
                "same_confirmed_cause": True,
                "similarity": 0.5,
            },
        )
    )
    session.flush()
    return incident


def golden_computation_result() -> RcaComputationResult:
    expected = json.loads(
        (FIXTURES / "golden_expected_analysis.json").read_text(encoding="utf-8")
    )
    events = [
        CanonicalEvent.model_validate_json(line)
        for line in (FIXTURES / "golden_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    event_by_source = {item.source_record_id: item for item in events}
    catalogue_payload = yaml.safe_load(
        (
            Path(__file__).resolve().parents[2]
            / "app"
            / "fixtures"
            / "hypotheses.yaml"
        ).read_text(encoding="utf-8")
    )
    catalogue = {
        item["hypothesis_type"]: item for item in catalogue_payload["hypotheses"]
    }
    candidates = tuple(
        HypothesisCandidate(
            candidate_id=f"candidate-{index}",
            hypothesis_type=item["hypothesis_type"],
            candidate_entity_id=item["candidate_entity_id"],
            generation_reason_codes=("CATALOGUE_RULE_MATCH",),
        )
        for index, item in enumerate(expected["hypotheses"], start=1)
    )
    ranked = tuple(
        RankedHypothesis(
            hypothesis_id=item["hypothesis_id"],
            candidate_id=candidates[index].candidate_id,
            hypothesis_type=item["hypothesis_type"],
            candidate_entity_id=item["candidate_entity_id"],
            rank=item["rank"],
            evidence_score=item["evidence_score"],
            evidence_coverage=EvidenceCoverage.model_validate(
                item["evidence_coverage"]
            ),
            factor_scores=item["factor_scores"],
            summary=item["summary"],
        )
        for index, item in enumerate(expected["hypotheses"])
    )
    conflicts = (
        ConflictEvidenceDraft(
            hypothesis_id="hyp_002",
            source_event_id=event_by_source[
                "prom-raw_ingress_requests_per_second-0241"
            ].event_id,
            statement="Gateway raw ingress remained stable.",
            relevance=0.95,
            reason_code="STABLE_RAW_INGRESS",
        ),
        ConflictEvidenceDraft(
            hypothesis_id="hyp_003",
            source_event_id=event_by_source[
                "prom-db_connection_utilization-0248"
            ].event_id,
            statement="Payment database utilization remained normal.",
            relevance=0.95,
            reason_code="NORMAL_DB_UTILIZATION",
        ),
    )
    return RcaComputationResult(
        candidates=candidates,
        ranked_hypotheses=ranked,
        conflict_evidence=conflicts,
        conflict_reason_codes=("STABLE_RAW_INGRESS", "NORMAL_DB_UTILIZATION"),
        topology_states=TopologyStates(
            nodes=(
                TopologyNodeState(
                    entity_id="api-gateway-01", state="suspected_root"
                ),
            )
        ),
        evidence_requirements={
            hypothesis_type: tuple(catalogue[hypothesis_type]["expected_evidence"])
            for hypothesis_type in (
                "configuration_regression",
                "dos_or_traffic_surge",
                "database_connection_exhaustion",
            )
        },
    )


def build_golden_analysis_bundle():
    """Build and detach the canonical P4 input used by RCA unit tests."""

    from sqlalchemy import create_engine

    from app.orchestration.analysis_bundle import build_incident_analysis_bundle

    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_golden_incident(session)
        bundle = build_incident_analysis_bundle(
            "inc_001",
            session,
            input_fingerprint=f"sha256:{'a' * 64}",
        )
    engine.dispose()
    return bundle
