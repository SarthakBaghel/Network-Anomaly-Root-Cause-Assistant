from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from .base import UtcModel
from .events import CanonicalEvent


class RawIngestionRequest(UtcModel):
    """One source-specific record plus its source-adapter identity."""

    source: str = Field(min_length=1)
    raw: dict[str, JsonValue]
    request_id: str | None = Field(default=None, min_length=1)


class IngestionMutationResponse(UtcModel):
    status: Literal["accepted", "collapsed", "quarantined"]
    request_id: str = Field(min_length=1)
    generated_at: datetime
    event_id: str | None = None
    quarantine_id: str | None = None
    collapsed_group_id: str | None = None
    representative_event_id: str | None = None
    source_record_id: str | None = None
    incident_id: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    analysis_state: Literal["not_started", "processed"] = "not_started"


class BatchIngestionResponse(UtcModel):
    request_id: str = Field(min_length=1)
    generated_at: datetime
    results: list[IngestionMutationResponse]


class EventListResponse(UtcModel):
    generated_at: datetime
    items: list[CanonicalEvent]
    next_cursor: str | None = None


class QuarantineItem(UtcModel):
    quarantine_id: str
    received_at: datetime
    validation_errors: list[dict[str, JsonValue]]
    raw_payload: dict[str, JsonValue]


class QuarantineListResponse(UtcModel):
    generated_at: datetime
    items: list[QuarantineItem]
