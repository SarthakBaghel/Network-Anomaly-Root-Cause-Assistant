from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .base import ReviewDecision, UtcModel


class ReviewRecord(UtcModel):
    review_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    analysis_run_id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    decision: ReviewDecision
    client_action_id: str = Field(min_length=1)
    requested_evidence_id: str | None
    reviewer: str = Field(min_length=1)
    comment: str
    created_at: datetime

    @model_validator(mode="after")
    def validate_evidence_request(self) -> "ReviewRecord":
        requested = self.decision is ReviewDecision.EVIDENCE_REQUESTED
        if requested != (self.requested_evidence_id is not None):
            raise ValueError("requested_evidence_id is required only for evidence_requested")
        return self


class ReviewRequest(UtcModel):
    analysis_run_id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    decision: ReviewDecision
    client_action_id: str = Field(min_length=1)
    requested_evidence_id: str | None = None
    reviewer: str = Field(min_length=1)
    comment: str = ""

    @model_validator(mode="after")
    def validate_evidence_request(self) -> "ReviewRequest":
        requested = self.decision is ReviewDecision.EVIDENCE_REQUESTED
        if requested != (self.requested_evidence_id is not None):
            raise ValueError("requested_evidence_id is required only for evidence_requested")
        return self
