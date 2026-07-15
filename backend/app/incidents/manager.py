from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models
from app.db.repositories import IncidentRepository, AuditRepository
from app.topology.graph import get_topology_graph, get_neighbors, get_path, topology_distance

# Load symptom families
import yaml
from pathlib import Path

def load_symptom_families() -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    yaml_path = Path(__file__).resolve().parents[1] / "fixtures" / "symptom_families.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    event_to_family = {}
    for family_name, family_data in data.get("families", {}).items():
        for event_type in family_data.get("event_types", []):
            event_to_family[event_type] = family_name
            
    incompatibilities = []
    for item in data.get("incompatibilities", []):
        incompatibilities.append((item["left"], item["right"], item.get("reason_code", "INCOMPATIBLE_SYMPTOM")))
        
    return event_to_family, incompatibilities

def check_symptom_compatibility(event_type: str, attached_event_types: list[str]) -> tuple[str, str | None]:
    event_to_family, incompatibilities = load_symptom_families()
    
    family = event_to_family.get(event_type)
    if not family:
        return "neutral", None
        
    attached_families = {event_to_family.get(et) for et in attached_event_types if event_to_family.get(et)}
    
    # Check incompatibilities
    for left, right, reason_code in incompatibilities:
        if (family == left and right in attached_families) or (family == right and left in attached_families):
            return "incompatible", reason_code
            
    # Check compatibility: if they share the same family
    if family in attached_families:
        return "compatible", None
        
    return "neutral", None

def get_topology_distance(source: str, target: str) -> int:
    from app.topology.graph import get_topology_graph
    import networkx as nx
    g = get_topology_graph().graph
    try:
        return nx.shortest_path_length(g.to_undirected(), source, target)
    except Exception:
        return 999

def make_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        from datetime import timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

class IncidentManager:
    """WS2B: Incident Management and Event Attachment (blueprint §12)."""

    def process_anomalies(
        self,
        anomalies: list[models.Anomaly],
        trigger_event: models.Event,
        session: Session,
    ) -> models.Incident | None:
        """Evaluate incoming anomalies and trigger event.
        
        Attempts to attach them to an existing open/investigating incident,
        or creates a new incident if threshold is exceeded and can_open_incident=True.
        """
        incident_repo = IncidentRepository(session)
        audit_repo = AuditRepository(session)

        # 1. Fetch all open/investigating incidents
        open_incidents = incident_repo.list_open()
        
        # We try to evaluate if the trigger event can attach to any open incident.
        attached_to_incident = None
        
        for incident in open_incidents:
            # Check if event is ineligible due to idle window / time constraint
            if make_naive(trigger_event.timestamp) > make_naive(incident.last_event_at) + timedelta(seconds=settings.incident_idle_window_seconds):
                self._record_eval(incident.id, trigger_event.id, "excluded", 0.0, ["IDLE_WINDOW_EXCEEDED"], incident_repo)
                continue
                
            # Score the trigger event against this incident
            score, reasons, has_rel = self.score_event(trigger_event, incident, session)
            
            # Attach if score >= threshold and has relationship
            if score >= settings.incident_attachment_threshold and has_rel:
                self._attach(incident.id, trigger_event, score, reasons, incident_repo, audit_repo)
                
                for anomaly in anomalies:
                    incident_repo.increment_anomaly_count(incident.id)
                
                incident_repo.update_last_event_at(incident.id, trigger_event.timestamp)
                
                affected = set(incident.affected_entity_ids)
                affected.add(trigger_event.entity_id)
                incident.affected_entity_ids = list(affected)
                
                attached_event_ids = [ev.event_id for ev in incident_repo.get_attached_events(incident.id)]
                stmt = select(models.Anomaly).where(models.Anomaly.event_id.in_(attached_event_ids), models.Anomaly.can_open_incident == True)
                attached_anoms = session.execute(stmt).scalars().all()
                if attached_anoms:
                    incident.severity = round(max(an.score for an in attached_anoms), 2)
                
                attached_to_incident = incident
                break
                
            else:
                self._record_eval(incident.id, trigger_event.id, "excluded", score, reasons, incident_repo)

        if attached_to_incident:
            return attached_to_incident

        # 2. If it did not attach, check if we can open a new incident
        opening_anomaly = None
        for anomaly in anomalies:
            if anomaly.score >= settings.incident_open_threshold and anomaly.can_open_incident and not anomaly.context_only:
                opening_anomaly = anomaly
                break

        if opening_anomaly is None:
            return None

        # Create new incident
        incident_id = f"inc_{uuid.uuid4().hex[:12]}"
        
        # Fetch lookback events
        lookback_cutoff = trigger_event.timestamp - timedelta(seconds=settings.incident_lookback_seconds)
        stmt_events = select(models.Event).where(
            models.Event.status == "accepted",
            models.Event.timestamp >= lookback_cutoff,
            models.Event.timestamp <= trigger_event.timestamp,
            models.Event.id != trigger_event.id
        ).order_by(models.Event.timestamp.asc(), models.Event.id.asc())
        lookback_events = session.execute(stmt_events).scalars().all()

        attached_events_list = [trigger_event]
        
        incident = models.Incident(
            id=incident_id,
            title=f"Checkout degradation through {trigger_event.entity_id}" if "gateway" in trigger_event.entity_id else f"Anomaly on {trigger_event.entity_id}",
            status="open",
            severity=round(opening_anomaly.score, 2),
            started_at=trigger_event.timestamp,
            last_event_at=trigger_event.timestamp,
            primary_entity_id=trigger_event.entity_id,
            affected_entity_ids=[trigger_event.entity_id],
            anomaly_count=len(anomalies),
            current_analysis_run_id=None,
            top_hypothesis_id=None,
            confirmed_hypothesis_id=None,
        )
        
        incident_repo.create(incident)

        # Evaluate lookback events
        for event in lookback_events:
            score, reasons, has_rel = self.score_event_for_lists(event, incident.primary_entity_id, trigger_event.timestamp, attached_events_list, session)
            if score >= settings.incident_attachment_threshold and has_rel:
                self._attach(incident.id, event, score, reasons, incident_repo, audit_repo)
                attached_events_list.append(event)
            else:
                self._record_eval(incident.id, event.id, "excluded", score, reasons, incident_repo)

        # Attach trigger event itself
        t_score, t_reasons, _ = self.score_event_for_lists(trigger_event, incident.primary_entity_id, trigger_event.timestamp, [], session)
        self._attach(incident.id, trigger_event, 1.0, t_reasons + ["TRIGGER_EVENT"], incident_repo, audit_repo)

        # Post-process incident attributes
        attached_events_list = sorted(attached_events_list, key=lambda e: (make_naive(e.timestamp), e.id))
        incident.started_at = attached_events_list[0].timestamp
        incident.last_event_at = attached_events_list[-1].timestamp
        
        affected_entities = list({e.entity_id for e in attached_events_list})
        incident.affected_entity_ids = affected_entities
        
        attached_event_ids = [e.id for e in attached_events_list]
        stmt_anoms_count = select(models.Anomaly).where(models.Anomaly.event_id.in_(attached_event_ids))
        all_attached_anoms = session.execute(stmt_anoms_count).scalars().all()
        incident.anomaly_count = len(all_attached_anoms)
        
        opening_anoms = [an.score for an in all_attached_anoms if an.can_open_incident]
        if opening_anoms:
            incident.severity = round(max(opening_anoms), 2)
            
        session.flush()

        # Audit incident opened
        audit_repo.append(
            audit_id=f"aud_{uuid.uuid4().hex}",
            actor_type="system",
            actor_id="incident_manager",
            action="INCIDENT_OPENED",
            object_type="incident",
            object_id=incident.id,
            payload={
                "started_at": incident.started_at.isoformat(),
                "primary_entity_id": incident.primary_entity_id,
                "severity": incident.severity,
            }
        )
        session.flush()
        
        return incident

    def score_event(self, event: models.Event, incident: models.Incident, session: Session) -> tuple[float, list[str], bool]:
        stmt = select(models.Event).join(models.IncidentEvent, models.IncidentEvent.event_id == models.Event.id).where(models.IncidentEvent.incident_id == incident.id)
        attached_events = list(session.execute(stmt).scalars())
        return self.score_event_for_lists(event, incident.primary_entity_id, incident.started_at, attached_events, session)

    def score_event_for_lists(
        self,
        event: models.Event,
        primary_entity_id: str,
        started_at: datetime,
        attached_events: list[models.Event],
        session: Session,
    ) -> tuple[float, list[str], bool]:
        score = 0.0
        reasons = []
        has_relationship = False

        if event.entity_id == primary_entity_id:
            score += 0.40
            reasons.append("SAME_ENTITY")
            has_relationship = True
        else:
            dist = get_topology_distance(event.entity_id, primary_entity_id)
            if dist == 1:
                score += 0.30
                reasons.append("ONE_TOPOLOGY_HOP")
                has_relationship = True
            elif dist == 2:
                score += 0.15
                reasons.append("TWO_TOPOLOGY_HOPS")
                has_relationship = True
            else:
                min_dist = 999
                for att in attached_events:
                    d = get_topology_distance(event.entity_id, att.entity_id)
                    if d < min_dist:
                        min_dist = d
                if min_dist == 1:
                    score += 0.30
                    reasons.append("ONE_TOPOLOGY_HOP")
                    has_relationship = True
                elif min_dist == 2:
                    score += 0.15
                    reasons.append("TWO_TOPOLOGY_HOPS")
                    has_relationship = True

        attached_traces = {att.trace_or_session_id for att in attached_events if att.trace_or_session_id}
        if event.trace_or_session_id:
            if event.trace_or_session_id in attached_traces:
                score += 0.40
                reasons.append("SHARED_TRACE_ID")
                has_relationship = True
            elif attached_traces:
                score -= 0.20
                reasons.append("DIFFERENT_TRACE_ID")

        attached_event_types = [att.event_type for att in attached_events]
        comp, reason_code = check_symptom_compatibility(event.event_type, attached_event_types)
        if comp == "compatible":
            score += 0.20
            reasons.append("COMPATIBLE_SYMPTOM")
        elif comp == "incompatible":
            score -= 0.25
            reasons.append(reason_code or "INCOMPATIBLE_SYMPTOM")

        if abs((make_naive(event.timestamp) - make_naive(started_at)).total_seconds()) <= 60:
            score += 0.10
            reasons.append("TEMPORAL_PROXIMITY_60S")

        score = max(-1.0, min(1.0, score))
        return score, reasons, has_relationship

    def _attach(self, incident_id: str, event: models.Event, score: float, reasons: list[str], incident_repo: IncidentRepository, audit_repo: AuditRepository) -> None:
        # Check if already attached to avoid unique constraint violations
        if incident_repo.is_event_attached(incident_id, event.id):
            return
        incident_repo.attach_event(models.IncidentEvent(
            incident_id=incident_id,
            event_id=event.id,
            attachment_score=score,
            attachment_reasons=reasons,
        ))
        self._record_eval(incident_id, event.id, "attached", score, reasons, incident_repo)
        
        audit_repo.append(
            audit_id=f"aud_{uuid.uuid4().hex}",
            actor_type="system",
            actor_id="incident_manager",
            action="EVENT_ATTACHED",
            object_type="event",
            object_id=event.id,
            payload={
                "incident_id": incident_id,
                "score": score,
                "reasons": reasons,
            }
        )

    def _record_eval(self, incident_id: str, event_id: str, decision: str, score: float, reasons: list[str], incident_repo: IncidentRepository) -> None:
        exists = incident_repo.session.get(models.IncidentEventEvaluation, (incident_id, event_id))
        if exists:
            return
        incident_repo.record_evaluation(models.IncidentEventEvaluation(
            incident_id=incident_id,
            event_id=event_id,
            decision=decision,
            attachment_score=score,
            attachment_reasons=reasons,
        ))
