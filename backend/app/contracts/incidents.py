from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import IncidentStatus, UtcModel


class IncidentSummary(UtcModel):
    incident_id: str = Field(min_length=1)
    current_analysis_run_id: str | None
    title: str = Field(min_length=1)
    status: IncidentStatus
    severity: float = Field(ge=0.0, le=1.0)
    started_at: datetime
    last_event_at: datetime
    primary_entity_id: str = Field(min_length=1)
    affected_entity_ids: list[str]
    anomaly_count: int = Field(ge=0)
    top_hypothesis_id: str | None
    confirmed_hypothesis_id: str | None


class IncidentListResponse(UtcModel):
    items: list[IncidentSummary]
    next_cursor: str | None = None
