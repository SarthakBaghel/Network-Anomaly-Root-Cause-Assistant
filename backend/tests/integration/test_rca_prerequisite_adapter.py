from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import models
from app.db.repositories import AnalysisRunRepository, IncidentRepository
from app.orchestration import AnalysisBuildContext, AnalysisOrchestrator
from app.orchestration.rca_adapter import RcaAdapterError, RcaAnalysisAdapter
from tests.support.rca_prerequisites import (
    golden_computation_result,
    seed_golden_incident,
)


class GoldenPureEngine:
    def __init__(self) -> None:
        self.calls = 0
        self.last_bundle = None

    def analyse(self, incident_bundle):
        self.calls += 1
        self.last_bundle = incident_bundle
        return golden_computation_result()


class FailingPureEngine:
    def analyse(self, incident_bundle):
        raise RuntimeError("internal database password must never be persisted")


def _database() -> tuple[object, Session]:
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    seed_golden_incident(session)
    session.commit()
    return engine, session


def test_adapter_binds_pure_result_to_pending_run_without_committing() -> None:
    engine, session = _database()
    try:
        session.add(
            models.AnalysisRun(
                id="run_pending",
                incident_id="inc_001",
                revision=1,
                status="building",
                trigger_event_id=None,
                input_fingerprint=f"sha256:{'b' * 64}",
                algorithm_version="rca-rules-1.1",
                created_at=datetime.fromisoformat("2026-07-14T09:32:00+00:00"),
                completed_at=None,
                failure_reason=None,
            )
        )
        session.flush()
        pure = GoldenPureEngine()
        result = RcaAnalysisAdapter(pure).analyse(
            IncidentRepository(session).get_by_id("inc_001"),
            session,
            AnalysisBuildContext("run_pending", "inc_001"),
        )

        assert pure.last_bundle.canonical_json()
        assert [row.rank for row in result.hypotheses] == [1, 2, 3]
        assert all(row.analysis_run_id == "run_pending" for row in result.hypotheses)
        assert set(result.conflict_reason_codes) == {
            "STABLE_RAW_INGRESS",
            "NORMAL_DB_UTILIZATION",
        }
        assert {row.reason_code for row in result.evidence_rows}.issuperset(
            result.conflict_reason_codes
        )
        assert result.topology_states.nodes[0].entity_id == "api-gateway-01"
        assert set(result.evidence_requirements) == {
            "configuration_regression",
            "dos_or_traffic_surge",
            "database_connection_exhaustion",
        }
        assert len(result.explanation_rows) == 1
        assert not session.execute(select(models.Hypothesis)).scalars().all()
    finally:
        session.close()
        engine.dispose()


def test_orchestrator_publishes_adapter_result_and_repeated_fingerprint_is_noop() -> None:
    engine, session = _database()
    try:
        pure = GoldenPureEngine()
        orchestrator = AnalysisOrchestrator()
        orchestrator.register_analysis_engine(RcaAnalysisAdapter(pure))

        orchestrator.recompute("inc_001", session)
        current = AnalysisRunRepository(session).get_current_for_incident("inc_001")
        assert current is not None
        assert pure.calls == 1
        assert len(session.execute(select(models.Hypothesis)).scalars().all()) == 3

        orchestrator.recompute("inc_001", session)
        assert pure.calls == 1
        assert len(AnalysisRunRepository(session).list_for_incident("inc_001")) == 1
    finally:
        session.close()
        engine.dispose()


def test_failed_pure_computation_preserves_prior_current_and_sanitizes_reason() -> None:
    engine, session = _database()
    try:
        successful = AnalysisOrchestrator()
        successful.register_analysis_engine(RcaAnalysisAdapter(GoldenPureEngine()))
        successful.recompute("inc_001", session)
        prior = AnalysisRunRepository(session).get_current_for_incident("inc_001")
        assert prior is not None

        event = session.scalar(
            select(models.Event).where(
                models.Event.source_record_id == "prom-forwarded_requests_per_second-0242"
            )
        )
        assert event is not None
        event.raw_payload = {**event.raw_payload, "changed_for_recompute": True}
        session.flush()
        failing = AnalysisOrchestrator()
        failing.register_analysis_engine(RcaAnalysisAdapter(FailingPureEngine()))

        try:
            failing.recompute("inc_001", session)
        except RcaAdapterError:
            pass
        else:
            raise AssertionError("failing pure engine did not raise")

        incident = IncidentRepository(session).get_by_id("inc_001")
        assert incident.current_analysis_run_id == prior.id
        assert AnalysisRunRepository(session).get_by_id(prior.id).status == "current"
        failed = session.execute(
            select(models.AnalysisRun).where(models.AnalysisRun.status == "failed")
        ).scalar_one()
        assert "pure RCA computation failed" in failed.failure_reason
        assert "database password" not in failed.failure_reason
    finally:
        session.close()
        engine.dispose()


def test_historical_lookup_failure_marks_pending_run_failed(monkeypatch) -> None:
    engine, session = _database()
    try:
        successful = AnalysisOrchestrator()
        successful.register_analysis_engine(RcaAnalysisAdapter(GoldenPureEngine()))
        successful.recompute("inc_001", session)
        prior = AnalysisRunRepository(session).get_current_for_incident("inc_001")
        assert prior is not None

        event = session.scalar(
            select(models.Event).where(
                models.Event.source_record_id == "prom-forwarded_requests_per_second-0242"
            )
        )
        assert event is not None
        event.raw_payload = {**event.raw_payload, "new_input": True}
        session.flush()

        def fail_history(_repository):
            raise RuntimeError("private historical store details")

        monkeypatch.setattr(
            "app.db.repositories.historical_incident_repository."
            "HistoricalIncidentRepository.list_all",
            fail_history,
        )
        failing = AnalysisOrchestrator()
        failing.register_analysis_engine(RcaAnalysisAdapter(GoldenPureEngine()))
        try:
            failing.recompute("inc_001", session)
        except RcaAdapterError:
            pass
        else:
            raise AssertionError("historical lookup failure did not raise")

        incident = IncidentRepository(session).get_by_id("inc_001")
        assert incident.current_analysis_run_id == prior.id
        failed = session.execute(
            select(models.AnalysisRun).where(models.AnalysisRun.status == "failed")
        ).scalar_one()
        assert "incident analysis bundle could not be assembled" in failed.failure_reason
        assert "private historical store" not in failed.failure_reason
    finally:
        session.close()
        engine.dispose()
