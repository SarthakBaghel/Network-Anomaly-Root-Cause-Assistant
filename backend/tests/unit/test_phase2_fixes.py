from __future__ import annotations

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import models
from app.db.models import Base
from app.db.repositories import HistoricalIncidentRepository
from app.orchestration.orchestrator import AnalysisOrchestrator, AnalysisEngineProtocol, AnalysisResult


def test_historical_incident_repository_queries() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    
    with Session(engine) as session:
        repo = HistoricalIncidentRepository(session)
        
        # 1. Create a historical incident
        hist = models.HistoricalIncident(
            id="hist_test_001",
            fingerprint="test-fingerprint-123",
            confirmed_cause="gateway_rate_limit_disabled",
            summary="Disabled rate limiter caused spike",
            feature_vector={"rps_jump": True}
        )
        repo.create(hist)
        
        # 2. Query by ID
        retrieved = repo.get_by_id("hist_test_001")
        assert retrieved is not None
        assert retrieved.fingerprint == "test-fingerprint-123"
        
        # 3. Query by Fingerprint
        by_fp = repo.get_by_fingerprint("test-fingerprint-123")
        assert by_fp is not None
        assert by_fp.id == "hist_test_001"
        
        # 4. List all
        all_items = repo.list_all()
        assert len(all_items) >= 1
        assert any(x.id == "hist_test_001" for x in all_items)


class BrokenAnalysisEngine(AnalysisEngineProtocol):
    """An engine that throws an exception during analysis to test failed run persistence."""
    def analyse(self, incident: models.Incident, session, context) -> AnalysisResult:
        raise RuntimeError("simulated engine crash")


def test_failed_analysis_run_persistence() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    
    with Session(engine) as session:
        # Set up basic DB entries for orchestrator run
        entity = models.Entity(
            id="api-gateway-01",
            name="API Gateway",
            entity_type="gateway",
            service="gateway",
            criticality="tier-1",
            metadata_json={}
        )
        session.add(entity)
        session.flush()

        incident = models.Incident(
            id="inc_fail_test",
            title="Gateway traffic spike",
            status="open",
            severity=0.8,
            started_at=datetime.now(timezone.utc),
            last_event_at=datetime.now(timezone.utc),
            primary_entity_id="api-gateway-01",
            affected_entity_ids=["api-gateway-01"],
            anomaly_count=1
        )
        session.add(incident)
        session.flush()
        
        # Instantiate orchestrator and register a crashing engine
        orc = AnalysisOrchestrator()
        orc.register_analysis_engine(BrokenAnalysisEngine())
        
        # Run pipeline should propagate the exception but persist the failed AnalysisRun row
        with pytest.raises(RuntimeError, match="simulated engine crash"):
            orc._run_rca_and_publish(incident, trigger_event=None, session=session)
            
        # Query AnalysisRun to verify the failed run is persisted
        stmt = (
            session.query(models.AnalysisRun)
            .filter(models.AnalysisRun.incident_id == "inc_fail_test")
            .all()
        )
        assert len(stmt) == 1
        run = stmt[0]
        assert run.status == "failed"
        assert "simulated engine crash" in run.failure_reason
