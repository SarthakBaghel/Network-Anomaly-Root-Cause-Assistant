from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "detector_rules.yaml"


@lru_cache(maxsize=1)
def detector_rules() -> dict[str, Any]:
    with CATALOGUE_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise RuntimeError("detector_rules.yaml must contain an object")
    return data


def log_rule(event_code: str) -> dict[str, Any] | None:
    return next(
        (rule for rule in detector_rules().get("log_rules", []) if rule.get("event_code") == event_code),
        None,
    )


def alert_severity(name: str) -> float:
    catalogue = detector_rules().get("alert_severity", {})
    return float(catalogue.get(name.lower(), 0.5))
