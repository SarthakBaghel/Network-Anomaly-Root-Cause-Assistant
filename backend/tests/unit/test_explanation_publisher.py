from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.contracts import ExplanationOutput
from app.db import models
from app.db.repositories import AnalysisRunRepository, IncidentRepository
from app.orchestration import (
    AnalysisBuildContext,
    AnalysisOrchestrator,
    AnalysisResult,
    ExplanationDraft,
)


NOW = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)


class StubExplanationEngine:
    def __init__(
        self,
        *,
        generators: tuple[str, ...] = ("template",),
        validated: bool = True,
        wrong_run: bool = False,
        wrong_incident: bool = False,
        fallback_reason: str | None = None,
        fallback_attempt_count: int = 0,
    ) -> None:
        self.generators = generators
        self.validated = validated
        self.wrong_run = wrong_run
        self.wrong_incident = wrong_incident
        self.fallback_reason = fallback_reason
        self.fallback_attempt_count = fallback_attempt_count
        self.context: AnalysisBuildContext | None = None

    def analyse(
        self,
        incident: models.Incident,
        session: Session,
        context: AnalysisBuildContext,
    ) -> AnalysisResult:
        self.context = context
        hypothesis = models.Hypothesis(
            id="hyp_new",
            analysis_run_id=context.analysis_run_id,
            incident_id=context.incident_id,
            type="configuration_regression",
            candidate_entity_id="api-gateway-01",
            rank=1,
            evidence_score=92.1,
            coverage={"available": 1, "expected": 1},
            factor_scores={},
            summary="A probable gateway configuration regression.",
        )
        drafts = [
            ExplanationDraft(
                output=ExplanationOutput(
                    analysis_run_id=(
                        "run_wrong" if self.wrong_run else context.analysis_run_id
                    ),
                    incident_id=(
                        "inc_wrong" if self.wrong_incident else context.incident_id
                    ),
                    hypothesis_id=hypothesis.id,
                    generator=generator,
                    summary=(
                        "The probable root cause is a gateway configuration "
                        "regression."
                    ),
                    claims=[
                        {
                            "claim": "A relevant configuration change preceded impact.",
                            "evidence_ids": ["ev_001"],
                        }
                    ],
                    diagnostic_step_ids=["inspect-config-diff"],
                    remediation_step_ids=["propose-config-rollback"],
                ),
                validated=self.validated,
            )
            for generator in self.generators
        ]
        return AnalysisResult(
            hypotheses=[hypothesis],
            evidence_rows=[],
            recommendation_rows=[],
            explanation_rows=drafts,
            explanation_fallback_reason=self.fallback_reason,
            explanation_fallback_attempt_count=self.fallback_attempt_count,
        )


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as database:
        database.add(
            models.Entity(
                id="api-gateway-01",
                name="API Gateway",
                entity_type="gateway",
                service="api-gateway",
                criticality="critical",
                metadata_json={},
            )
        )
        database.add(
            models.Event(
                id="evt_001",
                timestamp=NOW,
                ingested_at=NOW,
                entity_id="api-gateway-01",
                modality="metric",
                event_type="FORWARDED_REQUEST_RATE",
                severity=0.0,
                signal_name="forwarded_requests_per_second",
                signal_value=7800.0,
                unit="requests/s",
                trace_or_session_id="scenario_gateway_rate_limit_001",
                source="test",
                source_record_id="test-001",
                schema_version="1.0",
                quality_flags=[],
                raw_payload={},
                status="accepted",
            )
        )
        database.add(
            models.Incident(
                id="inc_001",
                title="Gateway incident",
                status="investigating",
                severity=0.91,
                started_at=NOW,
                last_event_at=NOW,
                primary_entity_id="api-gateway-01",
                affected_entity_ids=["api-gateway-01"],
                anomaly_count=1,
                current_analysis_run_id="run_prior",
                top_hypothesis_id="hyp_prior",
                confirmed_hypothesis_id=None,
            )
        )
        database.add(
            models.AnalysisRun(
                id="run_prior",
                incident_id="inc_001",
                revision=1,
                status="current",
                trigger_event_id="evt_001",
                input_fingerprint=f"sha256:{'a' * 64}",
                algorithm_version="rca-rules-1.1",
                created_at=NOW,
                completed_at=NOW,
                failure_reason=None,
            )
        )
        database.add(
            models.Hypothesis(
                id="hyp_prior",
                analysis_run_id="run_prior",
                incident_id="inc_001",
                type="dos_or_traffic_surge",
                candidate_entity_id="api-gateway-01",
                rank=1,
                evidence_score=50.0,
                coverage={"available": 1, "expected": 2},
                factor_scores={},
                summary="Prior hypothesis",
            )
        )
        database.add(
            models.IncidentEvent(
                incident_id="inc_001",
                event_id="evt_001",
                attachment_score=1.0,
                attachment_reasons=["SAME_ENTITY"],
            )
        )
        database.commit()
        yield database
    engine.dispose()


def _publish(session: Session, engine: StubExplanationEngine) -> models.AnalysisRun:
    orchestrator = AnalysisOrchestrator()
    orchestrator.register_analysis_engine(engine)
    orchestrator.recompute("inc_001", session)
    current = AnalysisRunRepository(session).get_current_for_incident("inc_001")
    assert current is not None
    return current


def test_template_only_persists_without_fallback_audit(session: Session) -> None:
    engine = StubExplanationEngine()
    current = _publish(session, engine)

    rows = list(
        session.execute(
            select(models.Explanation).where(
                models.Explanation.analysis_run_id == current.id
            )
        ).scalars()
    )
    assert engine.context == AnalysisBuildContext(current.id, "inc_001")
    assert len(rows) == 1
    assert rows[0].generator == "template"
    assert rows[0].validated is True
    assert rows[0].payload["analysis_run_id"] == current.id
    assert not list(
        session.execute(
            select(models.AuditLog).where(
                models.AuditLog.action == "EXPLANATION_FALLBACK_USED"
            )
        ).scalars()
    )


def test_template_and_llm_rows_are_appended_with_generators_preserved(
    session: Session,
) -> None:
    current = _publish(
        session, StubExplanationEngine(generators=("template", "llm"))
    )

    rows = list(
        session.execute(
            select(models.Explanation).where(
                models.Explanation.analysis_run_id == current.id
            )
        ).scalars()
    )
    assert {row.generator for row in rows} == {"template", "llm"}
    assert all(row.validated for row in rows)


def test_llm_fallback_writes_one_sanitized_audit_record(session: Session) -> None:
    current = _publish(
        session,
        StubExplanationEngine(
            fallback_reason="LLM_VALIDATION_FAILED",
            fallback_attempt_count=2,
        ),
    )

    rows = list(
        session.execute(
            select(models.AuditLog).where(
                models.AuditLog.action == "EXPLANATION_FALLBACK_USED"
            )
        ).scalars()
    )
    assert len(rows) == 1
    assert rows[0].payload == {
        "request_id": f"analysis:{current.id}",
        "analysis_run_id": current.id,
        "incident_id": "inc_001",
        "reason_code": "LLM_VALIDATION_FAILED",
        "attempt_count": 2,
    }


@pytest.mark.parametrize(
    "engine",
    [
        StubExplanationEngine(wrong_run=True),
        StubExplanationEngine(wrong_incident=True),
        StubExplanationEngine(validated=False),
        StubExplanationEngine(generators=("llm",)),
    ],
    ids=["wrong-run", "wrong-incident", "unvalidated", "missing-template"],
)
def test_invalid_explanation_fails_run_and_preserves_prior_current(
    session: Session,
    engine: StubExplanationEngine,
) -> None:
    orchestrator = AnalysisOrchestrator()
    orchestrator.register_analysis_engine(engine)

    with pytest.raises(ValueError):
        orchestrator.recompute("inc_001", session)

    incident = IncidentRepository(session).get_by_id("inc_001")
    assert incident is not None
    assert incident.current_analysis_run_id == "run_prior"
    assert AnalysisRunRepository(session).get_by_id("run_prior").status == "current"
    failed = session.execute(
        select(models.AnalysisRun).where(models.AnalysisRun.status == "failed")
    ).scalar_one()
    assert failed.completed_at is not None
    assert not list(
        session.execute(
            select(models.Explanation).where(
                models.Explanation.analysis_run_id == failed.id
            )
        ).scalars()
    )
    failure_audits = list(
        session.execute(
            select(models.AuditLog).where(
                models.AuditLog.action == "PIPELINE_STAGE_FAILED"
            )
        ).scalars()
    )
    assert len(failure_audits) == 1


def test_fallback_metadata_requires_sanitized_reason_and_attempt_count() -> None:
    with pytest.raises(ValueError, match="uppercase reason code"):
        AnalysisResult([], [], [], explanation_fallback_reason="raw failure details")
    with pytest.raises(ValueError, match="must be positive"):
        AnalysisResult([], [], [], explanation_fallback_reason="LLM_FAILED")
