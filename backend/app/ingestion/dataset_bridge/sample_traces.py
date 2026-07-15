"""
Sample Dataset (Distributed Trace) Reader
==========================================
Reads train.csv / val.csv / test.csv from data/sample_dataset/ and maps each
row to the first-class TraceAdapter payload. Dataset outcome fields are retained
only in ``_meta`` for offline evaluation and never influence runtime events.

Derivation rules (DatasetDescription.md §6):
    record_id   = "trace-{row_index:06d}"
    observed_at = BASE_TIMESTAMP + row_index * 5s
    host        = serviceName int -> service_id.yml name -> keyword -> frozen entity_id
    trace_id    = f"trace-{traceIdHigh:016x}{traceIdLow:016x}"
    p99         = latency_range.yml[operationName]["p99"]
    status      = "error" only when duration exceeds p99 * 3; this is derived
                  from observable telemetry, never from an outcome field

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
_VAL_CSV = "sample_dataset/val.csv"
_TEST_CSV = "sample_dataset/test.csv"

# id_manager files
_SERVICE_ID_YML = "sample_dataset/id_manager/service_id.yml"
_STATUS_ID_YML = "sample_dataset/id_manager/status_id.yml"
_LATENCY_YML = "sample_dataset/id_manager/latency_range.yml"

# Service name keyword -> frozen entity_id (longest match wins)
_KEYWORD_TO_ENTITY: list[tuple[str, str]] = [
    ("payment", "payment-api-01"),
    ("checkout", "checkout-api-01"),
    ("auth", "auth-api-01"),
    ("db", "payment-db-01"),
    ("gateway", "api-gateway-01"),
    ("order", "checkout-api-01"),
    ("cart", "checkout-api-01"),
    ("user", "auth-api-01"),
    ("product", "payment-api-01"),
]
_TRACE_SERVICE_RING = ("checkout-api-01", "payment-api-01", "auth-api-01")

_PROVENANCE = make_provenance(
    origin="sample_dataset",
    origin_record_id="test.csv",
    license_reference="CC-BY-4.0",
    synthetic_fields=[
        "record_id",
        "observed_at",
        "entity_id",
        "trace_id",
    ],
)


@lru_cache(maxsize=1)
def _load_service_id(data_root_str: str) -> dict[int, str]:
    """Load service_id.yml -> {integer_id: service_name}."""
    path = Path(data_root_str) / _SERVICE_ID_YML
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)  # {name: id}
    return {int(v): k for k, v in raw.items()}


@lru_cache(maxsize=1)
def _load_latency_range(data_root_str: str) -> dict[int, dict[str, float]]:
    """Load latency_range.yml -> {op_id: {mean, p99, std}}."""
    path = Path(data_root_str) / _LATENCY_YML
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)  # {op_id: {mean, p99, std}}
    return {int(k): v for k, v in raw.items() if isinstance(v, dict)}


def _entity_from_service_name(service_name: str) -> str:
    """Map a service name string to a frozen entity_id via keyword matching."""
    lower = service_name.lower()
    for keyword, entity_id in _KEYWORD_TO_ENTITY:
        if keyword in lower:
            return entity_id
    if service_name.isdigit():
        return _TRACE_SERVICE_RING[int(service_name) % len(_TRACE_SERVICE_RING)]
    return DEFAULT_ENTITY_ID


def _parse_row(
    row_idx: int,
    row: dict[str, str],
    svc_map: dict[int, str],
    lat_map: dict[int, dict[str, float]],
) -> dict[str, Any] | None:
    """Convert one dataset row to a TraceAdapter raw dict."""
    try:
        hi = int(row.get("traceIdHigh", 0) or 0)
        lo = int(row.get("traceIdLow", 0) or 0)

        svc_idx = int(row.get("serviceName", 2) or 2)
        svc_name = svc_map.get(svc_idx, f"service-{svc_idx}")
        entity_id = _entity_from_service_name(svc_name)

        op_id = int(row.get("operationName", 3) or 3)
        duration_ms = int(row.get("duration", 0) or 0)

        span_id = str(row.get("spanId") or f"span-{row_idx:06d}")
        parent_span_id = str(row.get("parentSpanId") or "0")
        if parent_span_id == "0":
            parent_span_id = None

        # Runtime threshold comes only from observable duration and the
        # operation baseline. Outcome columns remain offline-only metadata.
        op_lat = lat_map.get(op_id, {})
        p99 = float(op_lat.get("p99", 10.0))
        status = "error" if duration_ms > p99 * 3 else "ok"

    except (ValueError, TypeError):
        return None

    trace_id = f"trace-{hi:016x}{lo:016x}"
    ts = (BASE_TIMESTAMP + timedelta(seconds=row_idx * 5)).isoformat().replace("+00:00", "Z")
    record_id = f"trace-{row_idx:06d}"

    return {
        "scenario_id": SCENARIO_ID,
        "emitted_at": ts,
        "provenance": {**_PROVENANCE, "origin_record_id": f"test.csv row {row_idx}"},
        "_meta": {
            "node_latency_anomaly": int(row.get("nodeLatencyLabel", 0) or 0),
            "graph_latency_anomaly": int(row.get("graphLatencyLabel", 0) or 0),
            "graph_structure_anomaly": int(row.get("graphStructureLabel", 0) or 0),
            "duration_ms": duration_ms,
            "p99_threshold": p99,
            "service_name": svc_name,
            "dataset": "sample_dataset",
        },
        "payload": {
            "record_id": record_id,
            "span_id": span_id,
            "observed_at": ts,
            "entity_id": entity_id,
            "trace_id": trace_id,
            "parent_span_id": parent_span_id,
            "operation": f"operation-{op_id}",
            "duration_ms": duration_ms,
            "expected_p99_ms": p99,
            "status": status,
            "peer_service": None,
        },
    }


class SampleTracesReader(DatasetReader):
    """
    Yields TraceAdapter-compatible raw dicts from the distributed trace CSVs.

    The id_manager YAML files are loaded once and cached.  The latency_range.yml
    supplies the observable per-operation p99 used by the trace detector.

    Usage::

        reader = SampleTracesReader()
        for raw in reader.records(data_root, split="test"):
            result = pipeline.ingest(source=reader.source_name, raw=raw, ...)
    """

    source_name = "simulator.trace"
    default_limit = None  # small files — safe to read all rows

    def records(
        self,
        data_root: Path,
        *,
        limit: int | None = None,
        split: str = "test",  # "train" | "val" | "test"
    ) -> Iterator[dict[str, Any]]:
        """
        Yield one raw dict per trace span.

        Args:
            data_root: Absolute path to the project ``data/`` directory.
            limit:     Max rows to yield (None = all rows).
            split:     CSV file to read: "train", "val", or "test" (default).
                       Only "test" has anomaly label columns.
        """
        csv_map = {"train": _TRAIN_CSV, "val": _VAL_CSV, "test": _TEST_CSV}
        csv_path = data_root / csv_map.get(split, _TEST_CSV)
        if not csv_path.exists():
            raise FileNotFoundError(f"Sample dataset CSV not found at {csv_path}.")

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
