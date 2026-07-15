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
    status: Literal["healthy", "delayed", "offline", "quarantined", "error"]
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
    last_reset_at: datetime | None


class SimulatorScenario(UtcModel):
    scenario_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    affected_entity_ids: list[str] = Field(min_length=1)
    duration_seconds: int = Field(gt=0)
    expected_signals: list[str] = Field(min_length=1)
    difficulty: Literal["introductory", "intermediate", "advanced"]


class SimulatorScenarioListResponse(UtcModel):
    generated_at: datetime
    items: list[SimulatorScenario]


class SimulatorMutationResponse(SimulatorStatusResponse):
    request_id: str = Field(min_length=1)


class SimulatorResetResponse(SimulatorMutationResponse):
    reset_audit_id: str = Field(min_length=1)


class OverviewAnomaly(UtcModel):
    anomaly_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    entity_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    anomaly_type: str = Field(min_length=1)
    severity: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=1.0)
    detector_id: str = Field(min_length=1)
    detected_at: datetime
    context_only: bool
    can_open_incident: bool
    explanation: str = Field(min_length=1)


class AnomalyListResponse(UtcModel):
    generated_at: datetime
    items: list[OverviewAnomaly]
