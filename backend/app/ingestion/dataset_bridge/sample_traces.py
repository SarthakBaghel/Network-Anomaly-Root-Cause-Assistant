"""
Sample Dataset (Distributed Trace) Reader
==========================================
Reads train.csv / val.csv / test.csv from data/sample_dataset/ and maps
each trace span to the SyslogAdapter payload schema using the derivation
rules from DatasetDescription.md §6.

SyslogAdapter payload schema (required fields):
    payload.record_id    <- "trace-{row_index:06d}"
    payload.observed_at  <- BASE_TIMESTAMP + row_index * 5s  (ISO-8601 UTC)
    payload.host         <- serviceName index -> service_id.yml -> keyword -> entity_id
    payload.code         <- nodeLatencyLabel=1 or duration > p99*2 -> UPSTREAM_CONNECTION_TIMEOUT
                            else HEALTH_CHECK_OK

Optional syslog fields also populated:
    payload.level        <- "error" if anomalous, else "info"
    payload.message      <- human-readable span summary
    payload.facility     <- "distributed-trace"
    payload.trace_id     <- hex(traceIdHigh) + hex(traceIdLow)
    payload.attributes   <- {service, duration_ms, operation_name}

Derivation rules (DatasetDescription.md §6):
    record_id   = "trace-{row_index:06d}"
    observed_at = BASE_TIMESTAMP + row_index * 5s
    host        = serviceName int -> service_id.yml name -> keyword -> frozen entity_id
    trace_id    = f"trace-{traceIdHigh:016x}{traceIdLow:016x}"
    code        = UPSTREAM_CONNECTION_TIMEOUT if nodeLatencyLabel=1 or duration > p99*2
                  else HEALTH_CHECK_OK
    p99         = latency_range.yml[operationName]["p99"]
    facility    = "distributed-trace" (constant)

ID manager files used:
    id_manager/service_id.yml    -> integer service index -> service name string
    id_manager/status_id.yml     -> HTTP status string -> integer code index
    id_manager/latency_range.yml -> operation id -> {mean, p99, std} latency ms
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .base import (
    BASE_TIMESTAMP,
    DEFAULT_ENTITY_ID,
    SCENARIO_ID,
    DatasetReader,
    make_provenance,
)

# File paths relative to data_root
_TRAIN_CSV = "sample_dataset/train.csv"
_VAL_CSV   = "sample_dataset/val.csv"
_TEST_CSV  = "sample_dataset/test.csv"

# id_manager files
_SERVICE_ID_YML = "sample_dataset/id_manager/service_id.yml"
_STATUS_ID_YML  = "sample_dataset/id_manager/status_id.yml"
_LATENCY_YML    = "sample_dataset/id_manager/latency_range.yml"

# Service name keyword -> frozen entity_id (longest match wins)
_KEYWORD_TO_ENTITY: list[tuple[str, str]] = [
    ("payment",  "payment-api-01"),
    ("checkout", "checkout-api-01"),
    ("auth",     "auth-api-01"),
    ("db",       "payment-db-01"),
    ("gateway",  "api-gateway-01"),
    ("order",    "checkout-api-01"),
    ("cart",     "checkout-api-01"),
    ("user",     "auth-api-01"),
    ("product",  "payment-api-01"),
]

_PROVENANCE = make_provenance(
    origin="sample_dataset",
    origin_record_id="test.csv",
    license_reference="CC-BY-4.0",
    synthetic_fields=[
        "record_id", "observed_at", "host", "code", "trace_id", "attributes",
    ],
)


@lru_cache(maxsize=1)
def _load_service_id(data_root_str: str) -> dict[int, str]:
    """Load service_id.yml -> {integer_id: service_name}."""
    path = Path(data_root_str) / _SERVICE_ID_YML
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)   # {name: id}
    return {int(v): k for k, v in raw.items()}


@lru_cache(maxsize=1)
def _load_latency_range(data_root_str: str) -> dict[int, dict[str, float]]:
    """Load latency_range.yml -> {op_id: {mean, p99, std}}."""
    path = Path(data_root_str) / _LATENCY_YML
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)   # {op_id: {mean, p99, std}}
    return {int(k): v for k, v in raw.items() if isinstance(v, dict)}


def _entity_from_service_name(service_name: str) -> str:
    """Map a service name string to a frozen entity_id via keyword matching."""
    lower = service_name.lower()
    for keyword, entity_id in _KEYWORD_TO_ENTITY:
        if keyword in lower:
            return entity_id
    return DEFAULT_ENTITY_ID


def _parse_row(
    row_idx: int,
    row: dict[str, str],
    svc_map: dict[int, str],
    lat_map: dict[int, dict[str, float]],
) -> dict[str, Any] | None:
    """Convert one trace span row to a SyslogAdapter raw dict."""
    try:
        hi = int(row.get("traceIdHigh", 0) or 0)
        lo = int(row.get("traceIdLow",  0) or 0)

        svc_idx     = int(row.get("serviceName", 2) or 2)
        svc_name    = svc_map.get(svc_idx, f"service-{svc_idx}")
        entity_id   = _entity_from_service_name(svc_name)

        op_id       = int(row.get("operationName", 3) or 3)
        duration_ms = int(row.get("duration", 0)      or 0)

        # nodeLatencyLabel present in test.csv only; absent in train/val
        node_anomaly = int(row.get("nodeLatencyLabel", 0) or 0)

        # Lookup p99 threshold from latency_range.yml (DatasetDescription.md §6)
        op_lat = lat_map.get(op_id, {})
        p99    = float(op_lat.get("p99", 10.0))

        is_anomalous = bool(node_anomaly) or (duration_ms > p99 * 2)
        code  = "UPSTREAM_CONNECTION_TIMEOUT" if is_anomalous else "HEALTH_CHECK_OK"
        level = "error" if is_anomalous else "info"

    except (ValueError, TypeError):
        return None

    trace_id  = f"trace-{hi:016x}{lo:016x}"
    ts        = (BASE_TIMESTAMP + timedelta(seconds=row_idx * 5)).isoformat().replace("+00:00", "Z")
    record_id = f"trace-{row_idx:06d}"

    return {
        "scenario_id": SCENARIO_ID,
        "emitted_at":  ts,
        "provenance":  {**_PROVENANCE, "origin_record_id": f"test.csv row {row_idx}"},
        "_meta": {
            "node_latency_anomaly": node_anomaly,
            "duration_ms":          duration_ms,
            "p99_threshold":        p99,
            "service_name":         svc_name,
            "dataset":              "sample_dataset",
        },
        "payload": {
            "record_id":   record_id,
            "observed_at": ts,
            "host":        entity_id,
            "code":        code,
            "level":       level,
            "message":     f"Span svc={svc_name} dur={duration_ms}ms trace={trace_id[:16]}",
            "facility":    "distributed-trace",
            "trace_id":    trace_id,
            "attributes": {
                "service":         svc_name,
                "duration_ms":     duration_ms,
                "operation_id":    op_id,
                "p99_threshold_ms": p99,
            },
        },
    }


class SampleTracesReader(DatasetReader):
    """
    Yields SyslogAdapter-compatible raw dicts from the distributed trace CSVs.

    The id_manager YAML files are loaded once and cached.  The latency_range.yml
    is used to detect anomalous spans (duration > p99 * 2) as documented in
    DatasetDescription.md §6.

    Usage::

        reader = SampleTracesReader()
        for raw in reader.records(data_root, split="test"):
            result = pipeline.ingest(source=reader.source_name, raw=raw, ...)
    """

    source_name   = "simulator.syslog"
    default_limit = None   # small files — safe to read all rows

    def records(
        self,
        data_root: Path,
        *,
        limit: int | None = None,
        split: str = "test",   # "train" | "val" | "test"
    ) -> Iterator[dict[str, Any]]:
        """
        Yield one raw dict per trace span.

        Args:
            data_root: Absolute path to the project ``data/`` directory.
            limit:     Max rows to yield (None = all rows).
            split:     CSV file to read: "train", "val", or "test" (default).
                       Only "test" has anomaly label columns.
        """
        csv_map  = {"train": _TRAIN_CSV, "val": _VAL_CSV, "test": _TEST_CSV}
        csv_path = data_root / csv_map.get(split, _TEST_CSV)
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Sample dataset CSV not found at {csv_path}."
            )

        # Cache key must be a str (lru_cache doesn't support Path)
        data_root_str = str(data_root)
        svc_map = _load_service_id(data_root_str)
        lat_map = _load_latency_range(data_root_str)

        effective_limit = self._effective_limit(limit)
        yielded = 0

        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row_idx, row in enumerate(reader):
                record = _parse_row(row_idx, row, svc_map, lat_map)
                if record is not None:
                    yield record
                    yielded += 1
                    if effective_limit is not None and yielded >= effective_limit:
                        break


__all__ = ["SampleTracesReader"]
