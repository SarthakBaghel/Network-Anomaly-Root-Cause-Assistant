from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Anomaly,
    Base,
    Entity,
    Event,
    Incident,
    IncidentEvent,
    IncidentEventEvaluation,
)
from app.incidents.manager import IncidentManager

UTC = timezone.utc
TOPOLOGY_PATH = Path(__file__).resolve().parents[2] / "app" / "fixtures" / "topology.json"

def load_topology_into_db(session: Session) -> None:
    with open(TOPOLOGY_PATH, "r", encoding="utf-8") as f:
        topo = json.load(f)
    for node in topo["nodes"]:
        session.add(Entity(
            id=node["id"],
            name=node["name"],
            entity_type=node["entity_type"],
            service=node["service"],
            criticality=node["criticality"]
        ))
    session.flush()

def test_incident_manager_lookback_attachment_and_auth_exclusion() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    
    with Session(engine) as session:
        # Load topology
        load_topology_into_db(session)
        
        # Event 1: Config change at T+0 (gateway)
        t0 = datetime(2026, 7, 14, 9, 30, 0, tzinfo=UTC)
        ev_config = Event(
            id="evt_config", timestamp=t0, ingested_at=t0,
            entity_id="api-gateway-01", modality="config_change", event_type="CONFIG_VALUE_CHANGED",
            severity=0.0, signal_name=None, signal_value=None, unit=None,
            trace_or_session_id="scenario_gateway_rate_limit_001", source="test.config",
            source_record_id="config_0", schema_version="1.0", quality_flags=["SIMULATED"],
            raw_payload={"config_key": "rate_limit.enabled", "old_value": True, "new_value": False},
            status="accepted"
        )
        session.add(ev_config)
        
        # Anomaly for Event 1 (config change is context-only)
        an_config = Anomaly(
            id="ano_config", event_id="evt_config", detector_id="config_marker",
            type="CONFIG_VALUE_CHANGED", detected_at=t0, score=0.0, threshold=0.0,
            context_only=True, can_open_incident=False,
            window_start=t0, window_end=t0, features={}, explanation="Config changed"
        )
        session.add(an_config)
        session.flush()

        # Event 2: Metric spike at T+30 (gateway) - this will open the incident!
        t30 = t0 + timedelta(seconds=30)
        ev_spike = Event(
            id="evt_spike", timestamp=t30, ingested_at=t30,
            entity_id="api-gateway-01", modality="metric", event_type="FORWARDED_REQUEST_RATE",
            severity=0.86, signal_name="forwarded_requests_per_second", signal_value=7800.0, unit="requests/s",
            trace_or_session_id="scenario_gateway_rate_limit_001", source="test.prometheus",
            source_record_id="metric_1", schema_version="1.0", quality_flags=["SIMULATED"],
            raw_payload={}, status="accepted"
        )
        session.add(ev_spike)
        
        an_spike = Anomaly(
            id="ano_spike", event_id="evt_spike", detector_id="zscore",
            type="FORWARDED_TRAFFIC_SPIKE", detected_at=t30, score=0.91, threshold=0.75,
            context_only=False, can_open_incident=True,
            window_start=t30 - timedelta(minutes=5), window_end=t30, features={"observed": 7800.0},
            explanation="Traffic spike"
        )
        session.add(an_spike)
        session.flush()

        # Event 3: Auth expiry warning at T+120 (auth-api-01) - should be excluded!
        t120 = t0 + timedelta(seconds=120)
        ev_auth = Event(
            id="evt_auth", timestamp=t120, ingested_at=t120,
            entity_id="auth-api-01", modality="log", event_type="CERTIFICATE_EXPIRY_WARNING",
            severity=0.35, signal_name=None, signal_value=None, unit=None,
            trace_or_session_id="maintenance_auth_001", source="test.syslog",
            source_record_id="log_2", schema_version="1.0", quality_flags=["SIMULATED"],
            raw_payload={}, status="accepted"
        )
        session.add(ev_auth)
        
        an_auth = Anomaly(
            id="ano_auth", event_id="evt_auth", detector_id="log_rule",
            type="CERTIFICATE_MAINTENANCE_WARNING", detected_at=t120, score=0.30, threshold=0.75,
            context_only=False, can_open_incident=True,
            window_start=t120 - timedelta(minutes=5), window_end=t120, features={},
            explanation="Auth cert expiry"
        )
        session.add(an_auth)
        session.flush()

        # Instantiate IncidentManager and process anomalies for Event 2
        manager = IncidentManager()
        
        # 1. Process anomalies for Event 2
        inc = manager.process_anomalies([an_spike], ev_spike, session)
        assert inc is not None
        assert inc.primary_entity_id == "api-gateway-01"
        assert inc.status == "open"
        assert inc.severity == 0.91
        
        # Check started_at corresponds to lookback attached event (T+0 config change)
        assert inc.started_at == t0
        
        # Check that both ev_config and ev_spike are attached
        attached = session.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id)).all()
        attached_ids = {a.event_id for a in attached}
        assert "evt_config" in attached_ids
        assert "evt_spike" in attached_ids

        # A stable raw-ingress record has no anomaly, but the checked-in
        # evidence rule makes it relevant conflicting context for the RCA run.
        t90 = t0 + timedelta(seconds=90)
        ev_stable_ingress = Event(
            id="evt_stable_ingress",
            timestamp=t90,
            ingested_at=t90,
            entity_id="api-gateway-01",
            modality="metric",
            event_type="RAW_INGRESS_RATE",
            severity=0.0,
            signal_name="raw_ingress_requests_per_second",
            signal_value=7800.0,
            unit="requests/s",
            trace_or_session_id="scenario_gateway_rate_limit_001",
            source="test.prometheus",
            source_record_id="metric_stable_ingress",
            schema_version="1.0",
            quality_flags=["SIMULATED"],
            raw_payload={"source_distribution_changed": False},
            status="accepted",
        )
        session.add(ev_stable_ingress)
        session.flush()

        stable_result = manager.process_anomalies([], ev_stable_ingress, session)
        assert stable_result is inc
        stable_evaluation = session.get(
            IncidentEventEvaluation, (inc.id, ev_stable_ingress.id)
        )
        assert stable_evaluation is not None
        assert stable_evaluation.decision == "attached"
        assert session.get(IncidentEvent, (inc.id, ev_stable_ingress.id)) is not None
        
        # 2. Process anomalies for Event 3 (auth warning)
        inc_auth = manager.process_anomalies([an_auth], ev_auth, session)
        assert inc_auth is None
        
        # Verify evaluation decision is "excluded" for ev_auth
        evals = session.scalars(select(IncidentEventEvaluation).where(
            IncidentEventEvaluation.incident_id == inc.id,
            IncidentEventEvaluation.event_id == "evt_auth"
        )).all()
        assert len(evals) == 1
        assert evals[0].decision == "excluded"
        assert evals[0].attachment_score == -0.15
        assert evals[0].attachment_reasons == [
            "INCOMPATIBLE_MAINTENANCE_SYMPTOM",
            "EXPLICIT_DIFFERENT_TRACE",
        ]
        assert session.get(IncidentEvent, (inc.id, ev_auth.id)) is None


def test_context_only_anomaly_cannot_open_an_incident() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        load_topology_into_db(session)
        occurred_at = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)
        event = Event(
            id="evt_context_only",
            timestamp=occurred_at,
            ingested_at=occurred_at,
            entity_id="api-gateway-01",
            modality="config_change",
            event_type="CONFIG_VALUE_CHANGED",
            severity=0.0,
            signal_name=None,
            signal_value=None,
            unit=None,
            trace_or_session_id="scenario_context_only",
            source="test.config",
            source_record_id="context_only_1",
            schema_version="1.0",
            quality_flags=["SIMULATED"],
            raw_payload={"config_key": "rate_limit.enabled"},
            status="accepted",
        )
        anomaly = Anomaly(
            id="ano_context_only",
            event_id=event.id,
            detector_id="config_marker",
            type="RECENT_CONFIGURATION_CHANGE",
            detected_at=occurred_at,
            score=0.99,
            threshold=0.75,
            context_only=True,
            can_open_incident=True,
            window_start=occurred_at,
            window_end=occurred_at,
            features={},
            explanation="Context marker",
        )
        session.add_all([event, anomaly])
        session.flush()

        result = IncidentManager().process_anomalies([anomaly], event, session)

        assert result is None
        assert session.scalars(select(Incident)).all() == []


def test_every_considered_incident_persists_an_evaluation() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        load_topology_into_db(session)
        t0 = datetime(2026, 7, 14, 9, 30, tzinfo=UTC)

        def metric_event(event_id: str, offset: int) -> Event:
            occurred_at = t0 + timedelta(seconds=offset)
            return Event(
                id=event_id,
                timestamp=occurred_at,
                ingested_at=occurred_at,
                entity_id="api-gateway-01",
                modality="metric",
                event_type="FORWARDED_REQUEST_RATE",
                severity=0.9,
                signal_name="forwarded_requests_per_second",
                signal_value=7800.0,
                unit="requests/s",
                trace_or_session_id="scenario_shared",
                source="test.prometheus",
                source_record_id=event_id,
                schema_version="1.0",
                quality_flags=["SIMULATED"],
                raw_payload={},
                status="accepted",
            )

        older_anchor = metric_event("evt_older_anchor", 0)
        newer_anchor = metric_event("evt_newer_anchor", 10)
        candidate_event = metric_event("evt_multi_candidate", 20)
        older = Incident(
            id="inc_older",
            title="Older candidate incident",
            status="investigating",
            severity=0.9,
            started_at=older_anchor.timestamp,
            last_event_at=older_anchor.timestamp,
            primary_entity_id="api-gateway-01",
            affected_entity_ids=["api-gateway-01"],
            anomaly_count=1,
            current_analysis_run_id=None,
            top_hypothesis_id=None,
            confirmed_hypothesis_id=None,
        )
        newer = Incident(
            id="inc_newer",
            title="Newer candidate incident",
            status="investigating",
            severity=0.9,
            started_at=newer_anchor.timestamp,
            last_event_at=newer_anchor.timestamp,
            primary_entity_id="api-gateway-01",
            affected_entity_ids=["api-gateway-01"],
            anomaly_count=1,
            current_analysis_run_id=None,
            top_hypothesis_id=None,
            confirmed_hypothesis_id=None,
        )
        session.add_all(
            [older_anchor, newer_anchor, candidate_event, older, newer]
        )
        session.flush()
        session.add_all(
            [
                IncidentEvent(
                    incident_id=older.id,
                    event_id=older_anchor.id,
                    attachment_score=1.0,
                    attachment_reasons=["SAME_ENTITY"],
                ),
                IncidentEvent(
                    incident_id=newer.id,
                    event_id=newer_anchor.id,
                    attachment_score=1.0,
                    attachment_reasons=["SAME_ENTITY"],
                ),
            ]
        )
        anomaly = Anomaly(
            id="ano_multi_candidate",
            event_id=candidate_event.id,
            detector_id="zscore",
            type="FORWARDED_TRAFFIC_SPIKE",
            detected_at=candidate_event.timestamp,
            score=0.9,
            threshold=0.75,
            context_only=False,
            can_open_incident=True,
            window_start=t0,
            window_end=candidate_event.timestamp,
            features={},
            explanation="Traffic spike",
        )
        session.add(anomaly)
        session.flush()

        selected = IncidentManager().process_anomalies(
            [anomaly], candidate_event, session
        )

        assert selected is newer
        older_evaluation = session.get(
            IncidentEventEvaluation, (older.id, candidate_event.id)
        )
        newer_evaluation = session.get(
            IncidentEventEvaluation, (newer.id, candidate_event.id)
        )
        assert older_evaluation is not None
        assert older_evaluation.decision == "excluded"
        assert "BETTER_INCIDENT_MATCH" in older_evaluation.attachment_reasons
        assert newer_evaluation is not None
        assert newer_evaluation.decision == "attached"
        assert session.get(IncidentEvent, (older.id, candidate_event.id)) is None
        assert session.get(IncidentEvent, (newer.id, candidate_event.id)) is not None

        auth_time = t0 + timedelta(seconds=30)
        auth_event = Event(
            id="evt_multi_auth_warning",
            timestamp=auth_time,
            ingested_at=auth_time,
            entity_id="auth-api-01",
            modality="log",
            event_type="CERTIFICATE_EXPIRY_WARNING",
            severity=0.35,
            signal_name=None,
            signal_value=None,
            unit=None,
            trace_or_session_id="maintenance_auth_001",
            source="test.syslog",
            source_record_id="multi_auth_warning",
            schema_version="1.0",
            quality_flags=["SIMULATED"],
            raw_payload={},
            status="accepted",
        )
        auth_anomaly = Anomaly(
            id="ano_multi_auth_warning",
            event_id=auth_event.id,
            detector_id="log_rule",
            type="CERTIFICATE_MAINTENANCE_WARNING",
            detected_at=auth_time,
            score=0.3,
            threshold=0.75,
            context_only=False,
            can_open_incident=True,
            window_start=t0,
            window_end=auth_time,
            features={},
            explanation="Auth certificate warning",
        )
        session.add_all([auth_event, auth_anomaly])
        session.flush()

        excluded = IncidentManager().process_anomalies(
            [auth_anomaly], auth_event, session
        )

        assert excluded is None
        for incident_id in (older.id, newer.id):
            evaluation = session.get(
                IncidentEventEvaluation, (incident_id, auth_event.id)
            )
            assert evaluation is not None
            assert evaluation.decision == "excluded"
            assert session.get(IncidentEvent, (incident_id, auth_event.id)) is None
