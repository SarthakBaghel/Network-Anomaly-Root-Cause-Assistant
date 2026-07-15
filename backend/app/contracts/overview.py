from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .base import UtcModel


class SourceCounters(UtcModel):
    emitted: int = Field(ge=0)
    accepted: int = Field(ge=0)
    collapsed: int = Field(ge=0)
    quarantined: int = Field(ge=0)


class SourceHealth(UtcModel):
    source_id: str = Field(min_length=1)
    source_type: Literal["metrics", "logs", "alerts", "config_changes", "topology"]
    status: Literal["ready", "error"]
    last_ingest_at: datetime | None
    accepted: int = Field(ge=0)
    collapsed: int = Field(ge=0)
    quarantined: int = Field(ge=0)
    fixture_version: str | None = None


class SimulatorStatusResponse(UtcModel):
    generated_at: datetime
    state: Literal["stopped", "running", "paused", "ready", "triggering", "completed"]
    scenario_state: str = Field(min_length=1)
    scenario_id: str | None
    virtual_clock: datetime
    seed: int
    metric_interval_seconds: int = Field(gt=0)
    baseline_ticks_emitted: int = Field(ge=0)
    baseline_ticks_required: int = Field(ge=0)
    sources: dict[str, SourceCounters]
    source_health: list[SourceHealth]


class SimulatorMutationResponse(SimulatorStatusResponse):
    request_id: str = Field(min_length=1)


class SimulatorResetResponse(SimulatorMutationResponse):
    reset_audit_id: str = Field(min_length=1)


class OverviewAnomaly(UtcModel):
    anomaly_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    anomaly_type: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    detector_id: str = Field(min_length=1)
    detected_at: datetime


class AnomalyListResponse(UtcModel):
    generated_at: datetime
    items: list[OverviewAnomaly]
