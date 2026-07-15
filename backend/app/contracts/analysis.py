from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .base import AnalysisRunStatus, UtcModel


class AnalysisRun(UtcModel):
    analysis_run_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    status: AnalysisRunStatus
    trigger_event_id: str | None
    input_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]+$")
    created_at: datetime
    completed_at: datetime | None
    algorithm_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_completion(self) -> "AnalysisRun":
        if self.status is not AnalysisRunStatus.BUILDING and self.completed_at is None:
            raise ValueError("completed_at is required for non-building analysis runs")
        return self
