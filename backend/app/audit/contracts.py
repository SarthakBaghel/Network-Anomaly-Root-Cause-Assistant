"""Frozen input boundary for Person 5's append-only audit service."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from app.contracts.base import AuditActorType, FrozenModel


AUDIT_ACTION_CODES = frozenset(
    {
        "EVENT_QUARANTINED",
        "EVENT_COLLAPSED",
        "ANOMALY_DETECTED",
        "INCIDENT_OPENED",
        "EVENT_ATTACHED",
        "EVENT_EXCLUDED",
        "ANALYSIS_PUBLISHED",
        "PIPELINE_STAGE_FAILED",
        "EXPLANATION_FALLBACK_USED",
        "REVIEW_CONFIRMED",
        "REVIEW_REJECTED",
        "REVIEW_EVIDENCE_REQUESTED",
        "INCIDENT_STATUS_CHANGED",
        "DEMO_RESET",
    }
)

AuditAction = Literal[
    "EVENT_QUARANTINED",
    "EVENT_COLLAPSED",
    "ANOMALY_DETECTED",
    "INCIDENT_OPENED",
    "EVENT_ATTACHED",
    "EVENT_EXCLUDED",
    "ANALYSIS_PUBLISHED",
    "PIPELINE_STAGE_FAILED",
    "EXPLANATION_FALLBACK_USED",
    "REVIEW_CONFIRMED",
    "REVIEW_REJECTED",
    "REVIEW_EVIDENCE_REQUESTED",
    "INCIDENT_STATUS_CHANGED",
    "DEMO_RESET",
]

_RUN_SCOPED = {
    "ANALYSIS_PUBLISHED",
    "EXPLANATION_FALLBACK_USED",
    "REVIEW_CONFIRMED",
    "REVIEW_REJECTED",
    "REVIEW_EVIDENCE_REQUESTED",
    "INCIDENT_STATUS_CHANGED",
}
_INCIDENT_SCOPED = _RUN_SCOPED | {
    "INCIDENT_OPENED",
    "EVENT_ATTACHED",
    "EVENT_EXCLUDED",
    "PIPELINE_STAGE_FAILED",
}
_FORBIDDEN_METADATA_KEYS = {
    "raw_payload",
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "authorization",
    "stack_trace",
    "traceback",
}


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(
                marker in str(key).lower()
                for marker in _FORBIDDEN_METADATA_KEYS
            )
            or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


class AuditWrite(FrozenModel):
    """Validated, sanitized handoff consumed by the future audit service."""

    action: AuditAction
    actor_type: AuditActorType
    actor_id: str | None = None
    object_type: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    incident_id: str | None = None
    analysis_run_id: str | None = None
    analysis_revision: int | None = Field(default=None, ge=1)
    request_id: str = Field(min_length=1)
    reason_codes: list[str] = Field(default_factory=list)
    previous_state: str | None = None
    new_state: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope_and_safety(self) -> "AuditWrite":
        if self.action in _INCIDENT_SCOPED and self.incident_id is None:
            raise ValueError(f"incident_id is required for {self.action}")
        if self.action in _RUN_SCOPED:
            if self.analysis_run_id is None or self.analysis_revision is None:
                raise ValueError(
                    f"analysis_run_id and analysis_revision are required for {self.action}"
                )
        if self.action == "INCIDENT_STATUS_CHANGED" and (
            self.previous_state is None or self.new_state is None
        ):
            raise ValueError("status changes require previous_state and new_state")
        if _contains_forbidden_key(self.metadata):
            raise ValueError("audit metadata contains a forbidden raw or sensitive field")
        return self

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_id": self.request_id,
            **self.metadata,
        }
        optional = {
            "incident_id": self.incident_id,
            "analysis_run_id": self.analysis_run_id,
            "analysis_revision": self.analysis_revision,
            "reason_codes": self.reason_codes or None,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return payload
