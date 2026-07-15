from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.incidents import investigation
from app.db import models
from app.db.repositories import AnalysisRunRepository, IncidentRepository
from app.orchestration import AnalysisOrchestrator, RcaAdapterError, RcaAnalysisAdapter
from app.rca import AnalysisEngine, AnalysisEngineError
from tests.support.rca_prerequisites import (
    build_golden_analysis_bundle,
    seed_golden_incident,
)


class FailingEngine:
    def analyse(self, incident_bundle):
        raise AnalysisEngineError("deterministic ranking failed")


def _database():
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    seed_golden_incident(session)
    session.commit()
    return engine, session


def test_golden_anomaly_pipeline_produces_three_ranked_candidates() -> None:
    bundle = build_golden_analysis_bundle()
    first = AnalysisEngine().analyse(bundle)
    second = AnalysisEngine().analyse(bundle)

    assert len(first.candidates) == 3
    assert [item.hypothesis_type for item in first.ranked_hypotheses] == [
        "configuration_regression",
        "dos_or_traffic_surge",
        "database_connection_exhaustion",
    ]
    assert first.ranked_hypotheses[0].candidate_entity_id == "api-gateway-01"
    assert first.ranked_hypotheses[0].evidence_score == 92.1
    assert first.canonical_json() == second.canonical_json()


def test_real_engine_adapter_publication_is_atomic_and_idempotent() -> None:
    engine, session = _database()
    try:
        orchestrator = AnalysisOrchestrator()
        orchestrator.register_analysis_engine(RcaAnalysisAdapter(AnalysisEngine()))

        orchestrator.recompute("inc_001", session)
        current = AnalysisRunRepository(session).get_current_for_incident("inc_001")
        assert current is not None
        incident = IncidentRepository(session).get_by_id("inc_001")
        assert incident is not None
        assert incident.status == "investigating"
        hypotheses = list(
            session.execute(
                select(models.Hypothesis)
                .where(models.Hypothesis.analysis_run_id == current.id)
                .order_by(models.Hypothesis.rank)
            ).scalars()
        )
        assert [item.type for item in hypotheses] == [
            "configuration_regression",
            "dos_or_traffic_surge",
            "database_connection_exhaustion",
        ]
        assert hypotheses[0].evidence_score == 92.1
        conflicting = list(
            session.execute(
                select(models.Evidence)
                .where(
                    models.Evidence.analysis_run_id == current.id,
                    models.Evidence.kind == "conflicting",
                )
                .order_by(models.Evidence.reason_code)
            ).scalars()
        )
        assert {item.reason_code for item in conflicting}.issuperset(
            {"STABLE_RAW_INGRESS", "NORMAL_DB_UTILIZATION"}
        )
        assert current.typed_paths == {
            "configuration_traffic_impact": [
                "api-gateway-01",
                "checkout-api-01",
                "payment-api-01",
            ],
            "database_dependency": [
                "checkout-api-01",
                "payment-api-01",
                "payment-db-01",
            ],
        }
        assert set(current.conflict_reason_codes) == {
            "STABLE_RAW_INGRESS",
            "NORMAL_DB_UTILIZATION",
        }
        assert set(current.evidence_requirements) == {
            "configuration_regression",
            "dos_or_traffic_surge",
            "database_connection_exhaustion",
        }
        assert current.topology_states["nodes"]

        response = investigation("inc_001", session)
        response.assert_consistent_run()
        assert response.analysis_run_id == current.id
        assert {
            node.id: node.state for node in response.topology.nodes if node.state
        } == {
            item["entity_id"]: item["state"]
            for item in current.topology_states["nodes"]
        }

        orchestrator.recompute("inc_001", session)
        assert len(AnalysisRunRepository(session).list_for_incident("inc_001")) == 1
    finally:
        session.close()
        engine.dispose()


def test_failed_recomputation_leaves_prior_analysis_current() -> None:
    engine, session = _database()
    try:
        successful = AnalysisOrchestrator()
        successful.register_analysis_engine(RcaAnalysisAdapter(AnalysisEngine()))
        successful.recompute("inc_001", session)
        prior = AnalysisRunRepository(session).get_current_for_incident("inc_001")
        assert prior is not None

        event = session.scalar(
            select(models.Event).where(
                models.Event.source_record_id == "prom-forwarded_requests_per_second-0242"
            )
        )
        assert event is not None
        event.raw_payload = {**event.raw_payload, "new_revision_input": True}
        session.flush()
        failing = AnalysisOrchestrator()
        failing.register_analysis_engine(RcaAnalysisAdapter(FailingEngine()))
        try:
            failing.recompute("inc_001", session)
        except RcaAdapterError:
            pass
        else:
            raise AssertionError("failed analysis did not raise")

        session.close()
        with Session(engine, expire_on_commit=False) as verification:
            incident = IncidentRepository(verification).get_by_id("inc_001")
            assert incident.current_analysis_run_id == prior.id
            assert (
                AnalysisRunRepository(verification).get_by_id(prior.id).status
                == "current"
            )
            failed = verification.execute(
                select(models.AnalysisRun).where(models.AnalysisRun.status == "failed")
            ).scalar_one()
            assert failed.completed_at is not None
            failure_audit = verification.execute(
                select(models.AuditLog).where(
                    models.AuditLog.action == "PIPELINE_STAGE_FAILED",
                    models.AuditLog.object_id == "inc_001",
                )
            ).scalar_one()
            assert failure_audit.payload["analysis_run_id"] == failed.id
    finally:
        session.close()
        engine.dispose()
