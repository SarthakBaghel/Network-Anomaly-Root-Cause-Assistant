from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .base import EvidenceKind, UtcModel


class EvidenceItem(UtcModel):
    evidence_id: str = Field(min_length=1)
    analysis_run_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    kind: EvidenceKind
    source_event_id: str | None
    statement: str = Field(min_length=1)
    relevance: float = Field(ge=0.0, le=1.0)
    reason_code: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_source_event(self) -> "EvidenceItem":
        if (self.kind is EvidenceKind.MISSING) != (self.source_event_id is None):
            raise ValueError("source_event_id is null if and only if kind is missing")
        return self

