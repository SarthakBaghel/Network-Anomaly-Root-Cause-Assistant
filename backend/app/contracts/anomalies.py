from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .base import UtcModel


class AnomalyRecord(UtcModel):
    anomaly_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    detector_id: str = Field(min_length=1)
    detected_at: datetime
    anomaly_type: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    context_only: bool
    can_open_incident: bool
    window_start: datetime
    window_end: datetime
    features: dict[str, Any] = Field(default_factory=dict)
    explanation: str = Field(min_length=1)

