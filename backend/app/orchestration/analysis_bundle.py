"""Repository-backed assembly of immutable input for the pure RCA engine."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.contracts import AnomalyRecord, CanonicalEvent
from app.db import models
from app.db.repositories import (
    AnomalyRepository,
    EventRepository,
    HistoricalIncidentRepository,
    IncidentRepository,
)
from app.rca.contracts import (
    EventEvaluation,
    HistoricalMatch,
    IncidentAnalysisBundle,
    IncidentSnapshot,
    RcaTopologyEdge,
    RcaTopologyNode,
    RcaTopologySnapshot,
)
from app.topology.graph import TopologyGraph, get_topology_graph


class AnalysisBundleError(RuntimeError):
    """A sanitized domain failure while assembling deterministic RCA input."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _event_contract(row: models.Event) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=row.id,
        timestamp=_utc(row.timestamp),
        ingested_at=_utc(row.ingested_at),
        entity_id=row.entity_id,
        modality=row.modality,
        event_type=row.event_type,
        severity=row.severity,
        signal_name=row.signal_name,
        signal_value=row.signal_value,
        unit=row.unit,
        trace_or_session_id=row.trace_or_session_id,
        source=row.source,
        source_record_id=row.source_record_id,
        schema_version=row.schema_version,
        quality_flags=list(row.quality_flags or []),
        raw_payload=dict(row.raw_payload or {}),
    )


def _anomaly_contract(row: models.Anomaly) -> AnomalyRecord:
    return AnomalyRecord(
        anomaly_id=row.id,
        event_id=row.event_id,
        detector_id=row.detector_id,
        detected_at=_utc(row.detected_at),
        anomaly_type=row.type,
        score=row.score,
        threshold=row.threshold,
        context_only=row.context_only,
        can_open_incident=row.can_open_incident,
        window_start=_utc(row.window_start),
        window_end=_utc(row.window_end),
        features=dict(row.features or {}),
        explanation=row.explanation,
    )


def _topology_contract(topology: TopologyGraph) -> RcaTopologySnapshot:
    return RcaTopologySnapshot(
        fixture_version=topology.fixture_version,
        nodes=tuple(
            RcaTopologyNode(
                entity_id=row["id"],
                name=row["name"],
                entity_type=row["entity_type"],
                service=row["service"],
                criticality=row["criticality"],
            )
            for row in topology.node_records
        ),
        edges=tuple(
            RcaTopologyEdge(
                source=row["source"],
                target=row["target"],
                relation_type=row["relation_type"],
                relationship=row.get("relationship", row["relation_type"]),
            )
            for row in topology.edge_records
        ),
    )


def _feature_vector(
    entity: models.Entity,
    attached_events: tuple[CanonicalEvent, ...],
    anomalies: tuple[AnomalyRecord, ...],
) -> dict[str, Any]:
    vector: dict[str, Any] = {"entity_type": entity.entity_type}
    change = next(
        (
            event
            for event in attached_events
            if event.modality.value == "config_change"
            and isinstance(event.raw_payload.get("config_key"), str)
        ),
        None,
    )
    if change is not None:
        vector["change_type"] = change.raw_payload["config_key"]
    vector["forwarded_traffic_spike"] = any(
        anomaly.anomaly_type == "FORWARDED_TRAFFIC_SPIKE" for anomaly in anomalies
    )
    return vector


def _fallback_fingerprint(incident_id: str, event_ids: tuple[str, ...]) -> str:
    payload = "|".join((incident_id, *event_ids)).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _historical_matches(
    repository: HistoricalIncidentRepository,
    *,
    fingerprint: str,
    feature_vector: dict[str, Any],
) -> tuple[HistoricalMatch, ...]:
    rows = repository.list_all()
    causes = tuple(dict.fromkeys(row.confirmed_cause for row in rows))
    best_by_id: dict[str, HistoricalMatch] = {}
    for cause in causes:
        for match in repository.find_similarity_matches(
            candidate_cause=cause,
            fingerprint=fingerprint,
            feature_vector=feature_vector,
        ):
            previous = best_by_id.get(match.historical_incident_id)
            if previous is None or match.similarity > previous.similarity:
                best_by_id[match.historical_incident_id] = match
    return tuple(
        sorted(
            best_by_id.values(),
            key=lambda item: (-item.similarity, item.historical_incident_id),
        )
    )


def build_incident_analysis_bundle(
    incident_id: str,
    session: Session,
    *,
    input_fingerprint: str | None = None,
    topology: TopologyGraph | None = None,
) -> IncidentAnalysisBundle:
    """Load incident state once and detach it from the SQLAlchemy identity map."""

    incident_repo = IncidentRepository(session)
    incident = incident_repo.get_by_id(incident_id)
    if incident is None:
        raise AnalysisBundleError("incident not found")
    primary_entity = session.get(models.Entity, incident.primary_entity_id)
    if primary_entity is None:
        raise AnalysisBundleError("incident primary entity does not resolve")

    attached_rows = incident_repo.get_attached_events(incident_id)
    attached_ids = {row.event_id for row in attached_rows}
    event_rows = EventRepository(session).get_events_by_ids(sorted(attached_ids))
    event_by_id = {row.id: row for row in event_rows}
    if set(event_by_id) != attached_ids:
        raise AnalysisBundleError("an attached event does not resolve")
    attached_events = tuple(
        _event_contract(row)
        for row in sorted(event_rows, key=lambda item: (_utc(item.timestamp), item.id))
    )

    anomaly_rows = AnomalyRepository(session).list_by_events(sorted(attached_ids))
    anomalies = tuple(_anomaly_contract(row) for row in anomaly_rows)

    excluded_rows = sorted(
        (
            row
            for row in incident_repo.get_all_evaluations(incident_id)
            if row.decision == "excluded"
        ),
        key=lambda row: row.event_id,
    )
    excluded_event_rows = EventRepository(session).get_events_by_ids(
        [row.event_id for row in excluded_rows]
    )
    excluded_by_id = {row.id: row for row in excluded_event_rows}
    if set(excluded_by_id) != {row.event_id for row in excluded_rows}:
        raise AnalysisBundleError("an excluded event does not resolve")
    excluded_evaluations = tuple(
        EventEvaluation(
            event=_event_contract(excluded_by_id[row.event_id]),
            attachment_score=row.attachment_score,
            attachment_reasons=tuple(row.attachment_reasons or []),
        )
        for row in sorted(
            excluded_rows,
            key=lambda item: (
                _utc(excluded_by_id[item.event_id].timestamp),
                item.event_id,
            ),
        )
    )

    feature_vector = _feature_vector(primary_entity, attached_events, anomalies)
    fingerprint = input_fingerprint or _fallback_fingerprint(
        incident_id, tuple(event.event_id for event in attached_events)
    )
    historical = _historical_matches(
        HistoricalIncidentRepository(session),
        fingerprint=fingerprint,
        feature_vector=feature_vector,
    )

    return IncidentAnalysisBundle(
        incident=IncidentSnapshot(
            incident_id=incident.id,
            title=incident.title,
            status=incident.status,
            severity=incident.severity,
            started_at=_utc(incident.started_at),
            last_event_at=_utc(incident.last_event_at),
            primary_entity_id=incident.primary_entity_id,
            primary_entity_type=primary_entity.entity_type,
            affected_entity_ids=tuple(incident.affected_entity_ids or []),
            anomaly_count=incident.anomaly_count,
        ),
        attached_events=attached_events,
        anomalies=anomalies,
        excluded_evaluations=excluded_evaluations,
        topology=_topology_contract(topology or get_topology_graph()),
        historical_matches=historical,
    )


__all__ = ["AnalysisBundleError", "build_incident_analysis_bundle"]
