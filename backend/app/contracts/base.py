from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class UtcModel(FrozenModel):
    @field_validator("*", mode="after")
    @classmethod
    def normalize_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must include a timezone")
            return value.astimezone(timezone.utc)
        return value


class Modality(str, Enum):
    METRIC = "metric"
    LOG = "log"
    ALERT = "alert"
    CONFIG_CHANGE = "config_change"


class EventStatus(str, Enum):
    ACCEPTED = "accepted"
    QUARANTINED = "quarantined"
    COLLAPSED = "collapsed"


class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class EvidenceKind(str, Enum):
    OBSERVED = "observed"
    CORRELATED = "correlated"
    CONFLICTING = "conflicting"
    MISSING = "missing"


class ReviewDecision(str, Enum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EVIDENCE_REQUESTED = "evidence_requested"


class AuditActorType(str, Enum):
    SYSTEM = "system"
    USER = "user"
    LLM = "llm"


class TopologyRelation(str, Enum):
    DEPENDS_ON = "depends_on"
    SENDS_TRAFFIC_TO = "sends_traffic_to"


class AnalysisRunStatus(str, Enum):
    BUILDING = "building"
    CURRENT = "current"
    SUPERSEDED = "superseded"
    FAILED = "failed"
