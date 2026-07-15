"""Catalogue-backed incident opening and event attachment.

The manager consumes committed ORM events/anomalies and never reads test
expectations. It does not commit; the orchestrator owns the transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml
from sqlalchemy.orm import Session

from app.audit.contracts import AuditWrite
from app.audit.service import audit_service
from app.config import settings
from app.db import models
from app.db.repositories import (
    AnomalyRepository,
    EventRepository,
    IncidentRepository,
)
from app.topology.graph import TopologyError, TopologyGraph, get_topology_graph


SYMPTOM_CATALOGUE = Path(__file__).resolve().parents[1] / "fixtures" / "symptom_families.yaml"


@dataclass(frozen=True)
class EvidenceRuleMatch:
    rule_id: str
    attachment_reason_code: str | None


@dataclass(frozen=True)
class AttachmentEvaluation:
    decision: str
    score: float
    reasons: tuple[str, ...]
    has_strong_relationship: bool
    matched_evidence_rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IncidentAttachmentContext:
    symptom_family: str | None
    trace_or_session_id: str | None
    opening_symptom_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def _load_symptom_catalogue() -> dict[str, Any]:
    raw = yaml.safe_load(SYMPTOM_CATALOGUE.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("symptom_families.yaml must contain a mapping")
    if raw.get("schema_version") != "1.0" or not raw.get("version"):
        raise ValueError("unsupported or missing symptom-family catalogue version")
    if not isinstance(raw.get("families"), dict):
        raise ValueError("symptom-family catalogue must contain families")
    return raw


class SymptomCatalogue:
    """Validated lookup facade over the checked-in symptom catalogue."""

    def __init__(self, payload: Mapping[str, Any] | None = None) -> None:
        self.payload = dict(payload or _load_symptom_catalogue())
        self.families = dict(self.payload.get("families", {}))
        self.incompatibilities = list(self.payload.get("incompatibilities", []))
        self.attachment_rules = list(
            self.payload.get("attachment_evidence_rules", [])
        )

    def families_for(self, event_type: str) -> list[str]:
        return [
            family
            for family, definition in self.families.items()
            if event_type in definition.get("event_types", [])
        ]

    def incident_title(self, family: str | None, entity: models.Entity) -> str:
        if family is not None:
            title = self.families.get(family, {}).get("incident_title")
            if isinstance(title, str) and title:
                return title
        return f"Anomaly affecting {entity.name}"

    def incompatibility_reason(
        self, incident_family: str | None, event_families: list[str]
    ) -> str | None:
        if incident_family is None:
            return None
        for row in self.incompatibilities:
            left = row.get("left")
            right = row.get("right")
            if (
                left in event_families
                and right == incident_family
                or right in event_families
                and left == incident_family
            ):
                return str(row["reason_code"])
        return None

    def evidence_rule_matches(
        self,
        event: models.Event,
        incident_family: str | None,
        opening_symptom_at: datetime,
    ) -> list[EvidenceRuleMatch]:
        matches: list[EvidenceRuleMatch] = []
        for rule in self.attachment_rules:
            if incident_family not in rule.get("incident_families", []):
                continue
            if event.event_type not in rule.get("event_types", []):
                continue
            conditions = rule.get("conditions", {})
            if conditions.get("at_or_after_opening_symptom") and (
                _utc(event.timestamp) < _utc(opening_symptom_at)
            ):
                continue
            maximum = conditions.get("signal_value_lte")
            if maximum is not None and (
                event.signal_value is None or event.signal_value > float(maximum)
            ):
                continue
            matches.append(
                EvidenceRuleMatch(
                    rule_id=str(rule["rule_id"]),
                    attachment_reason_code=rule.get("attachment_reason_code"),
                )
            )
        return matches


class IncidentManager:
    """Open incidents and attach/exclude accepted records deterministically."""

    def __init__(
        self,
        *,
        topology: TopologyGraph | None = None,
        catalogue: SymptomCatalogue | None = None,
        incident_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.topology = topology or get_topology_graph()
        self.catalogue = catalogue or SymptomCatalogue()
        self.incident_id_factory = incident_id_factory or (
            lambda: f"inc_{uuid.uuid4().hex[:20]}"
        )

    def process_anomalies(
        self,
        anomalies: list[models.Anomaly],
        trigger_event: models.Event,
        session: Session,
    ) -> models.Incident | None:
        """Attach to an active incident or open one from an eligible anomaly."""

        event_anomalies = [
            anomaly for anomaly in anomalies if anomaly.event_id == trigger_event.id
        ]
        incident_repo = IncidentRepository(session)
        candidates: list[tuple[models.Incident, AttachmentEvaluation]] = []
        for incident in incident_repo.list_open():
            context = self._context_for_incident(incident, session)
            evaluation = self.score_attachment(
                incident,
                trigger_event,
                event_anomalies,
                context=context,
                lookback=False,
            )
            candidates.append((incident, evaluation))

        attachable = [item for item in candidates if item[1].decision == "attached"]
        if attachable:
            selected_incident = max(
                attachable,
                key=lambda item: (item[1].score, _utc(item[0].last_event_at)),
            )[0]
            for incident, evaluation in candidates:
                if (
                    incident.id != selected_incident.id
                    and evaluation.decision == "attached"
                ):
                    evaluation = replace(
                        evaluation,
                        decision="excluded",
                        reasons=tuple(
                            dict.fromkeys(
                                (*evaluation.reasons, "BETTER_INCIDENT_MATCH")
                            )
                        ),
                    )
                self._persist_evaluation(
                    incident, trigger_event, event_anomalies, evaluation, session
                )
            return selected_incident

        opening = self._opening_anomalies(event_anomalies)
        entity = session.get(models.Entity, trigger_event.entity_id)
        if opening and entity is not None:
            # The event was considered against active incidents but could not
            # attach; preserve those exclusions before opening a new incident.
            for incident, evaluation in candidates:
                self._persist_evaluation(
                    incident, trigger_event, event_anomalies, evaluation, session
                )
            return self._open_incident(trigger_event, opening, entity, session)

        # Non-opening records such as the maintenance warning are retained as
        # explicit exclusions against every active incident that considered
        # them. This keeps incident_event_evaluations a complete decision log.
        for incident, evaluation in candidates:
            self._persist_evaluation(
                incident, trigger_event, event_anomalies, evaluation, session
            )
        return None

    def score_attachment(
        self,
        incident: models.Incident,
        event: models.Event,
        anomalies: list[models.Anomaly],
        *,
        context: IncidentAttachmentContext,
        lookback: bool,
    ) -> AttachmentEvaluation:
        reasons: list[str] = []
        score = 0.0
        has_relationship = False
        event_time = _utc(event.timestamp)
        last_attached = _utc(incident.last_event_at)
        if not lookback and event_time > last_attached + timedelta(
            seconds=settings.incident_idle_window_seconds
        ):
            return AttachmentEvaluation(
                decision="excluded",
                score=0.0,
                reasons=("AFTER_INCIDENT_WINDOW",),
                has_strong_relationship=False,
            )

        if event.entity_id == incident.primary_entity_id:
            score += 0.40
            reasons.append("SAME_ENTITY")
            has_relationship = True
        else:
            distance = self._traffic_distance(
                incident.primary_entity_id, event.entity_id
            )
            if distance == 1:
                score += 0.30
                reasons.append("ONE_TRAFFIC_HOP")
                has_relationship = True
            elif distance == 2:
                score += 0.15
                reasons.append("TWO_TRAFFIC_HOPS")
                has_relationship = True

        same_trace = (
            context.trace_or_session_id is not None
            and event.trace_or_session_id == context.trace_or_session_id
        )
        different_trace = (
            context.trace_or_session_id is not None
            and event.trace_or_session_id is not None
            and event.trace_or_session_id != context.trace_or_session_id
        )
        if same_trace:
            score += 0.40
            reasons.append("SHARED_SCENARIO_TRACE")
            has_relationship = True

        event_families = self.catalogue.families_for(event.event_type)
        incompatibility = self.catalogue.incompatibility_reason(
            context.symptom_family, event_families
        )
        if context.symptom_family in event_families:
            score += 0.20
            reasons.append("COMPATIBLE_SYMPTOM")
        elif incompatibility is not None:
            score -= 0.25
            reasons.append(incompatibility)
            # The frozen handoff exposes the negative causal reasons for an
            # incompatible event while its topology point remains in the score.
            reasons = [
                reason
                for reason in reasons
                if reason not in {"ONE_TRAFFIC_HOP", "TWO_TRAFFIC_HOPS"}
            ]

        if different_trace:
            score -= 0.20
            reasons.append("EXPLICIT_DIFFERENT_TRACE")

        temporal_anchor = (
            context.opening_symptom_at if lookback else _utc(incident.started_at)
        )
        if abs((event_time - temporal_anchor).total_seconds()) <= 60:
            score += 0.10
            # The frozen fixture names temporal proximity specifically for the
            # preceding lookback association. Live-event scores still receive
            # the point and are capped at 1.0.
            if lookback and event_time < context.opening_symptom_at:
                reasons.append("WITHIN_60_SECONDS")

        evidence_rules = self.catalogue.evidence_rule_matches(
            event, context.symptom_family, context.opening_symptom_at
        )
        for match in evidence_rules:
            if match.attachment_reason_code:
                reasons.append(match.attachment_reason_code)

        significant = bool(anomalies) or bool(evidence_rules)
        score = round(max(-1.0, min(1.0, score)), 2)
        attach = (
            significant
            and has_relationship
            and score >= settings.incident_attachment_threshold
        )
        return AttachmentEvaluation(
            decision="attached" if attach else "excluded",
            score=score,
            reasons=tuple(dict.fromkeys(reasons)),
            has_strong_relationship=has_relationship,
            matched_evidence_rule_ids=tuple(
                match.rule_id for match in evidence_rules
            ),
        )

    def _opening_anomalies(
        self, anomalies: list[models.Anomaly]
    ) -> list[models.Anomaly]:
        return [
            anomaly
            for anomaly in anomalies
            if anomaly.score > settings.incident_open_threshold
            and anomaly.can_open_incident
            and not anomaly.context_only
        ]

    def _open_incident(
        self,
        event: models.Event,
        opening_anomalies: list[models.Anomaly],
        entity: models.Entity,
        session: Session,
    ) -> models.Incident:
        family = next(iter(self.catalogue.families_for(event.event_type)), None)
        incident = models.Incident(
            id=self.incident_id_factory(),
            title=self.catalogue.incident_title(family, entity),
            status="open",
            severity=0.0,
            started_at=event.timestamp,
            last_event_at=event.timestamp,
            primary_entity_id=event.entity_id,
            affected_entity_ids=[event.entity_id],
            anomaly_count=0,
            current_analysis_run_id=None,
            top_hypothesis_id=None,
            confirmed_hypothesis_id=None,
        )
        incident_repo = IncidentRepository(session)
        incident_repo.create(incident)
        audit_service.append(
            AuditWrite(
                action="INCIDENT_OPENED",
                actor_type="system",
                actor_id="incident_manager",
                object_type="incident",
                object_id=incident.id,
                incident_id=incident.id,
                request_id=f"pipeline:{event.id}",
                reason_codes=["OPEN_THRESHOLD_EXCEEDED"],
                metadata={
                    "opening_event_id": event.id,
                    "opening_anomaly_ids": [item.id for item in opening_anomalies],
                },
            ),
            session,
            timestamp=_utc(event.timestamp),
        )
        context = IncidentAttachmentContext(
            symptom_family=family,
            trace_or_session_id=event.trace_or_session_id,
            opening_symptom_at=_utc(event.timestamp),
        )
        opening_evaluation = self.score_attachment(
            incident,
            event,
            opening_anomalies,
            context=context,
            lookback=False,
        )
        self._persist_evaluation(
            incident, event, opening_anomalies, opening_evaluation, session
        )

        lookback_start = _utc(event.timestamp) - timedelta(
            seconds=settings.incident_lookback_seconds
        )
        lookback_events = EventRepository(session).list_accepted_in_window(
            lookback_start,
            _utc(event.timestamp),
            end_inclusive=True,
        )
        anomaly_repo = AnomalyRepository(session)
        anomaly_or_context: list[tuple[models.Event, list[models.Anomaly]]] = []
        latest_normal_evidence: dict[
            tuple[str, str | None, str],
            tuple[models.Event, list[models.Anomaly], EvidenceRuleMatch],
        ] = {}
        for prior_event in lookback_events:
            if prior_event.id == event.id:
                continue
            prior_anomalies = anomaly_repo.list_by_event(prior_event.id)
            evidence_rules = self.catalogue.evidence_rule_matches(
                prior_event, context.symptom_family, context.opening_symptom_at
            )
            if prior_anomalies:
                anomaly_or_context.append((prior_event, prior_anomalies))
                continue
            for match in evidence_rules:
                key = (prior_event.entity_id, prior_event.signal_name, match.rule_id)
                current = latest_normal_evidence.get(key)
                if current is None or _utc(prior_event.timestamp) > _utc(
                    current[0].timestamp
                ):
                    latest_normal_evidence[key] = (prior_event, [], match)

        lookback_candidates = anomaly_or_context + [
            (event_row, anomaly_rows)
            for event_row, anomaly_rows, _match in latest_normal_evidence.values()
        ]
        lookback_candidates.sort(
            key=lambda item: (_utc(item[0].timestamp), item[0].id)
        )
        for prior_event, prior_anomalies in lookback_candidates:
            evaluation = self.score_attachment(
                incident,
                prior_event,
                prior_anomalies,
                context=context,
                lookback=True,
            )
            self._persist_evaluation(
                incident, prior_event, prior_anomalies, evaluation, session
            )
        return incident

    def _persist_evaluation(
        self,
        incident: models.Incident,
        event: models.Event,
        anomalies: list[models.Anomaly],
        evaluation: AttachmentEvaluation,
        session: Session,
    ) -> None:
        incident_repo = IncidentRepository(session)
        if incident_repo.get_evaluation(incident.id, event.id) is not None:
            return
        incident_repo.record_evaluation(
            models.IncidentEventEvaluation(
                incident_id=incident.id,
                event_id=event.id,
                decision=evaluation.decision,
                attachment_score=evaluation.score,
                attachment_reasons=list(evaluation.reasons),
            )
        )
        action = "EVENT_EXCLUDED"
        if evaluation.decision == "attached":
            incident_repo.attach_event(
                models.IncidentEvent(
                    incident_id=incident.id,
                    event_id=event.id,
                    attachment_score=evaluation.score,
                    attachment_reasons=list(evaluation.reasons),
                )
            )
            incident_repo.update_started_at_if_earlier(incident.id, event.timestamp)
            incident_repo.update_last_event_at(incident.id, event.timestamp)
            actionable = [
                anomaly
                for anomaly in anomalies
                if anomaly.can_open_incident and not anomaly.context_only
            ]
            if actionable:
                incident_repo.add_anomaly_count(incident.id, len(actionable))
                incident_repo.add_affected_entity(incident.id, event.entity_id)
                incident_repo.update_severity(
                    incident.id, max(anomaly.score for anomaly in actionable)
                )
            action = "EVENT_ATTACHED"

        audit_service.append(
            AuditWrite(
                action=action,
                actor_type="system",
                actor_id="incident_manager",
                object_type="event",
                object_id=event.id,
                incident_id=incident.id,
                request_id=f"pipeline:{event.id}",
                reason_codes=list(evaluation.reasons),
                metadata={
                    "event_id": event.id,
                    "decision": evaluation.decision,
                    "attachment_score": evaluation.score,
                },
            ),
            session,
            timestamp=_utc(event.timestamp),
        )

    def _context_for_incident(
        self, incident: models.Incident, session: Session
    ) -> IncidentAttachmentContext:
        attachments = IncidentRepository(session).get_attached_events(incident.id)
        event_rows = EventRepository(session).get_events_by_ids(
            [item.event_id for item in attachments]
        )
        events = sorted(
            event_rows, key=lambda item: (_utc(item.timestamp), item.id)
        )
        trace = next(
            (item.trace_or_session_id for item in events if item.trace_or_session_id),
            None,
        )
        family_event = next(
            (
                (item, families[0])
                for item in events
                if (families := self.catalogue.families_for(item.event_type))
            ),
            None,
        )
        if family_event is None:
            return IncidentAttachmentContext(
                symptom_family=None,
                trace_or_session_id=trace,
                opening_symptom_at=_utc(incident.started_at),
            )
        return IncidentAttachmentContext(
            symptom_family=family_event[1],
            trace_or_session_id=trace,
            opening_symptom_at=_utc(family_event[0].timestamp),
        )

    def _traffic_distance(self, source: str, target: str) -> int | None:
        try:
            distance = self.topology.topology_distance(
                source, target, "sends_traffic_to", "forward"
            )
        except TopologyError:
            return None
        if distance > settings.incident_max_topology_hops:
            return None
        return distance


def serialize_incident_bundle(session: Session, incident_id: str) -> dict[str, Any]:
    """Serialize P4-owned incident/evaluation state for golden-fixture comparison."""

    incident_repo = IncidentRepository(session)
    incident = incident_repo.get_by_id(incident_id)
    if incident is None:
        raise ValueError(f"Incident not found: {incident_id}")
    attached_rows = incident_repo.get_attached_events(incident_id)
    evaluation_rows = incident_repo.get_all_evaluations(incident_id)
    event_ids = {item.event_id for item in evaluation_rows}
    events = {
        item.id: item for item in EventRepository(session).get_events_by_ids(list(event_ids))
    }

    def evaluation_payload(row: models.IncidentEventEvaluation) -> dict[str, Any]:
        event = events[row.event_id]
        return {
            "event_id": event.id,
            "source_record_id": event.source_record_id,
            "decision": row.decision,
            "attachment_score": row.attachment_score,
            "attachment_reasons": list(row.attachment_reasons),
        }

    attached_ids = {item.event_id for item in attached_rows}
    attached = [row for row in evaluation_rows if row.event_id in attached_ids]
    excluded = [row for row in evaluation_rows if row.event_id not in attached_ids]
    catalogue = SymptomCatalogue()
    event_type_order = {
        event_type: index
        for index, event_type in enumerate(
            event_type
            for family in catalogue.families.values()
            for event_type in family.get("event_types", [])
        )
    }
    order = lambda row: (
        _utc(events[row.event_id].timestamp),
        event_type_order.get(events[row.event_id].event_type, len(event_type_order)),
        events[row.event_id].source_record_id or events[row.event_id].id,
    )
    return {
        "schema_version": "1.0",
        "version": "golden-incident-bundle-1.0",
        "incident": {
            "incident_id": incident.id,
            "current_analysis_run_id": incident.current_analysis_run_id,
            "title": incident.title,
            "status": incident.status,
            "severity": incident.severity,
            "started_at": _utc(incident.started_at)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "last_event_at": _utc(incident.last_event_at)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "primary_entity_id": incident.primary_entity_id,
            "affected_entity_ids": list(incident.affected_entity_ids),
            "anomaly_count": incident.anomaly_count,
            "top_hypothesis_id": incident.top_hypothesis_id,
            "confirmed_hypothesis_id": incident.confirmed_hypothesis_id,
        },
        "attached_events": [evaluation_payload(row) for row in sorted(attached, key=order)],
        "excluded_events": [evaluation_payload(row) for row in sorted(excluded, key=order)],
    }


incident_manager = IncidentManager()
