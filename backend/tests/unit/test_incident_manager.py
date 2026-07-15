from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.contracts import CanonicalEvent
from app.db.models import Anomaly, Base, Entity, Event, Incident, IncidentEvent, IncidentEventEvaluation
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
