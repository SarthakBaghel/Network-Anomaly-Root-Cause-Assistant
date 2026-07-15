from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit.contracts import AUDIT_ACTION_CODES, AuditWrite
from app.audit.service import AuditService
from app.db import models


RUN_SCOPED = {
    "ANALYSIS_PUBLISHED",
    "EXPLANATION_FALLBACK_USED",
    "REVIEW_CONFIRMED",
    "REVIEW_REJECTED",
    "REVIEW_EVIDENCE_REQUESTED",
    "INCIDENT_STATUS_CHANGED",
}
INCIDENT_SCOPED = RUN_SCOPED | {
    "INCIDENT_OPENED",
    "EVENT_ATTACHED",
    "EVENT_EXCLUDED",
    "PIPELINE_STAGE_FAILED",
}


def _write(action: str, index: int) -> AuditWrite:
    return AuditWrite(
        action=action,
        actor_type="system",
        actor_id="audit-service-test",
        object_type="incident" if action in INCIDENT_SCOPED else "system",
        object_id="inc_001" if action in INCIDENT_SCOPED else f"object_{index}",
        incident_id="inc_001" if action in INCIDENT_SCOPED else None,
        analysis_run_id="run_007" if action in RUN_SCOPED else None,
        analysis_revision=7 if action in RUN_SCOPED else None,
        request_id=f"req_{index}",
        reason_codes=["TEST_REASON"],
        previous_state=(
            "investigating" if action == "INCIDENT_STATUS_CHANGED" else None
        ),
        new_state="resolved" if action == "INCIDENT_STATUS_CHANGED" else None,
        metadata={"subject_id": f"subject_{index}"},
    )


def test_service_appends_every_frozen_action_and_exposes_no_mutators() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    service = AuditService()
    with factory() as session:
        for index, action in enumerate(sorted(AUDIT_ACTION_CODES), start=1):
            service.append(
                _write(action, index),
                session,
                audit_id=f"aud_action_{index}",
            )
        rows = list(session.execute(select(models.AuditLog)).scalars())
        assert {row.action for row in rows} == set(AUDIT_ACTION_CODES)
        assert all(row.payload["request_id"] for row in rows)

    assert not hasattr(service, "update")
    assert not hasattr(service, "delete")
    engine.dispose()
