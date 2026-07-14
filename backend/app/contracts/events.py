from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from .base import Modality, UtcModel


class CanonicalEvent(UtcModel):
    event_id: str = Field(min_length=1)
    timestamp: datetime
    ingested_at: datetime
    entity_id: str = Field(min_length=1)
    modality: Modality
    event_type: str = Field(min_length=1)
    severity: float = Field(ge=0.0, le=1.0)
    signal_name: str | None = None
    signal_value: float | None = None
    unit: str | None = None
    trace_or_session_id: str | None = None
    source: str = Field(min_length=1)
    source_record_id: str | None = None
    schema_version: str = Field(min_length=1)
    quality_flags: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_metric_fields(self) -> "CanonicalEvent":
        values = (self.signal_name, self.signal_value, self.unit)
        if self.modality is Modality.METRIC and any(value is None for value in values):
            raise ValueError("metric events require signal_name, signal_value, and unit")
        return self

