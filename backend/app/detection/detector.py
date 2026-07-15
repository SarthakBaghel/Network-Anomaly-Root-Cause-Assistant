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


def _profile_aliases() -> dict[str, str]:
    """Return the signal_aliases mapping from network_profile.json.

    Keys are dataset-specific or proxy signal names; values are the
    canonical monitored signal names used by the z-score detector.
    BLUEPRINT §3.3.4: proxy mappings must be labelled as such.
    """
    with PROFILE_PATH.open(encoding="utf-8") as handle:
        profile = json.load(handle)
    raw = profile.get("signal_aliases", {})
    # Strip metadata comment key
    return {k: v for k, v in raw.items() if not k.startswith("_")}


@dataclass(frozen=True)
class DetectionContext:
    history: list[CanonicalEvent] = field(default_factory=list)
    safety_thresholds: dict[str, float] = field(default_factory=_profile_thresholds)
    signal_aliases: dict[str, str] = field(default_factory=_profile_aliases)
    detected_at: datetime | None = None


class Detector(Protocol):
    detector_id: str

    def evaluate(
        self,
        event: CanonicalEvent,
        context: DetectionContext,
    ) -> list[AnomalyRecord]: ...
