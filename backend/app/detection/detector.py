from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.contracts import AnomalyRecord, CanonicalEvent


PROFILE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "reference_profiles" / "network_profile.json"


def _profile_thresholds() -> dict[str, float]:
    with PROFILE_PATH.open(encoding="utf-8") as handle:
        profile = json.load(handle)
    return {
        name: float(values["safety_threshold"])
        for name, values in profile["signals"].items()
        if "safety_threshold" in values
    }


@dataclass(frozen=True)
class DetectionContext:
    history: list[CanonicalEvent] = field(default_factory=list)
    safety_thresholds: dict[str, float] = field(default_factory=_profile_thresholds)
    detected_at: datetime | None = None


class Detector(Protocol):
    detector_id: str

    def evaluate(
        self,
        event: CanonicalEvent,
        context: DetectionContext,
    ) -> list[AnomalyRecord]: ...
