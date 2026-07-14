from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _integer(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}, got {value}")
    return value


def _ratio(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric, got {raw!r}") from exc
    if not 0.0 <= value <= 1.0:
        raise RuntimeError(f"{name} must be between 0.0 and 1.0, got {value}")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    explanation_mode: str
    simulator_seed: int
    simulator_metric_interval_seconds: int
    detector_window_seconds: int
    detector_min_baseline_points: int
    metric_zscore_threshold: float
    anomaly_threshold: float
    incident_open_threshold: float
    incident_lookback_seconds: int
    incident_idle_window_seconds: int
    incident_max_topology_hops: int
    incident_attachment_threshold: float
    duplicate_bucket_seconds: int
    event_batch_max_items: int
    event_max_payload_bytes: int
    frontend_poll_interval_ms: int


def load_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./network_anomaly_rca.db")
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("DATABASE_URL must use synchronous sqlite:/// for the MVP")
    database_path = database_url.removeprefix("sqlite:///")
    if not database_path.startswith("/"):
        database_url = f"sqlite:///{(REPOSITORY_ROOT / database_path).resolve()}"
    explanation_mode = os.getenv("EXPLANATION_MODE", "template")
    if explanation_mode not in {"template", "llm"}:
        raise RuntimeError("EXPLANATION_MODE must be 'template' or 'llm'")
    zscore = float(os.getenv("METRIC_ZSCORE_THRESHOLD", "3.0"))
    if zscore <= 0:
        raise RuntimeError("METRIC_ZSCORE_THRESHOLD must be positive")
    return Settings(
        database_url=database_url,
        explanation_mode=explanation_mode,
        simulator_seed=_integer("SIMULATOR_SEED", 20260714, minimum=0),
        simulator_metric_interval_seconds=_integer("SIMULATOR_METRIC_INTERVAL_SECONDS", 10),
        detector_window_seconds=_integer("DETECTOR_WINDOW_SECONDS", 300),
        detector_min_baseline_points=_integer("DETECTOR_MIN_BASELINE_POINTS", 20),
        metric_zscore_threshold=zscore,
        anomaly_threshold=_ratio("ANOMALY_THRESHOLD", 0.75),
        incident_open_threshold=_ratio("INCIDENT_OPEN_THRESHOLD", 0.75),
        incident_lookback_seconds=_integer("INCIDENT_LOOKBACK_SECONDS", 300),
        incident_idle_window_seconds=_integer("INCIDENT_IDLE_WINDOW_SECONDS", 300),
        incident_max_topology_hops=_integer("INCIDENT_MAX_TOPOLOGY_HOPS", 2),
        incident_attachment_threshold=_ratio("INCIDENT_ATTACHMENT_THRESHOLD", 0.40),
        duplicate_bucket_seconds=_integer("DUPLICATE_BUCKET_SECONDS", 10),
        event_batch_max_items=_integer("EVENT_BATCH_MAX_ITEMS", 100),
        event_max_payload_bytes=_integer("EVENT_MAX_PAYLOAD_BYTES", 65536),
        frontend_poll_interval_ms=_integer("FRONTEND_POLL_INTERVAL_MS", 1500),
    )


settings = load_settings()
