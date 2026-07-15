"""
NSL-KDD Dataset Reader
=======================
Reads KDDTrain+_20Percent.txt (ARFF text format without header) and maps
each row to the PrometheusAdapter payload schema using the derivation rules
from DatasetDescription.md §1 (synthetic columns).

PrometheusAdapter payload schema (required fields):
    payload.sample_id    <- "kdd-train-{row_index:06d}"
    payload.observed_at  <- BASE_TIMESTAMP + row_index * 10s  (ISO-8601 UTC)
    payload.metric       <- one of the 6 derived signal names
    payload.value        <- float derived from KDD columns
    payload.unit         <- per-signal unit string
    payload.labels.entity_id <- SERVICE_TO_ENTITY[service_column]

Derivation rules (DatasetDescription.md §1):
    raw_ingress_requests_per_second  = src_bytes / 1500 / max(duration, 1)  [clip 0..15000]
    forwarded_requests_per_second    = count / max(duration, 1)              [clip 0..15000]
    active_connections_total         = dst_host_count                        (direct)
    connection_utilization           = dst_host_srv_count / 255.0            [clip 0..1]
    tcp_resets_total                 = wrong_fragment + urgent
    tcp_retransmissions_total        = rerror_rate * count

Attack -> hypothesis vocabulary (used for provenance only, not injected at runtime):
    neptune/smurf/back/teardrop  -> dos_or_traffic_surge
    ipsweep/portsweep/satan      -> external_probe
    rootkit/buffer_overflow      -> configuration_regression
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

from .base import (
    BASE_TIMESTAMP,
    HYPOTHESIS_MAP,
    SCENARIO_ID,
    DatasetReader,
    entity_from_service,
    make_provenance,
)

# File path relative to data_root
_ARFF_TXT = "nsl_kdd/KDDTrain+_20Percent.txt"

# Column index map (NSL-KDD ARFF, 0-indexed, from the ARFF @attribute header)
_COL = {
    "duration":         0,
    "service":          2,
    "src_bytes":        4,
    "wrong_fragment":   7,
    "urgent":           8,
    "count":            22,
    "rerror_rate":      26,
    "dst_host_count":   31,
    "dst_host_srv_count": 32,
    "class":            41,

}

# Ordered list of (signal_name, unit) — rotated round-robin across rows
# so each ingestion session produces all 6 signal types
_SIGNALS: list[tuple[str, str]] = [
    ("raw_ingress_requests_per_second", "requests/s"),
    ("forwarded_requests_per_second",   "requests/s"),
    ("active_connections_total",        "connections"),
    ("connection_utilization",          "ratio"),
    ("tcp_resets_total",                "count/10s"),
    ("tcp_retransmissions_total",       "count/10s"),
]

_PROVENANCE = make_provenance(
    origin="NSL-KDD",
    origin_record_id="KDDTrain+_20Percent.txt",
    license_reference="CC-BY-4.0",
    synthetic_fields=[
        "sample_id", "observed_at", "metric", "value",
        "unit", "entity_id", "labels",
    ],
)


def _derive_signal(
    row_idx: int,
    duration: float,
    src_bytes: float,
    wrong_fragment: float,
    urgent: float,
    count: float,
    rerror_rate: float,
    dst_host_count: float,
    dst_host_srv_count: float,
) -> tuple[str, float, str]:
    """Return (signal_name, value, unit) for a given row index."""
    sig_name, unit = _SIGNALS[row_idx % len(_SIGNALS)]

    raw_values = {
        "raw_ingress_requests_per_second": min(src_bytes / 1500.0 / duration, 15000.0),
        "forwarded_requests_per_second":   min(count / duration, 15000.0),
        "active_connections_total":        dst_host_count,
        "connection_utilization":          min(dst_host_srv_count / 255.0, 1.0),
        "tcp_resets_total":                wrong_fragment + urgent,
        "tcp_retransmissions_total":       rerror_rate * count,
    }
    return sig_name, raw_values[sig_name], unit


def _parse_row(row_idx: int, cols: list[str]) -> dict[str, Any] | None:
    """
    Convert one raw CSV line (43 columns) into a PrometheusAdapter raw dict.
    Returns None if the row is malformed.
    """
    if len(cols) < 43:
        return None

    try:
        duration         = max(float(cols[_COL["duration"]]),          1.0)
        service          = cols[_COL["service"]].strip()
        src_bytes        = float(cols[_COL["src_bytes"]])
        wrong_fragment   = float(cols[_COL["wrong_fragment"]])
        urgent           = float(cols[_COL["urgent"]])
        count            = float(cols[_COL["count"]])
        rerror_rate      = float(cols[_COL["rerror_rate"]])
        dst_host_count   = float(cols[_COL["dst_host_count"]])
        dst_host_srv_cnt = float(cols[_COL["dst_host_srv_count"]])
        klass            = cols[_COL["class"]].strip()
    except (ValueError, IndexError):
        return None

    entity_id = entity_from_service(service)
    ts        = (BASE_TIMESTAMP + timedelta(seconds=row_idx * 10)).isoformat().replace("+00:00", "Z")
    sample_id = f"kdd-train-{row_idx:06d}"

    sig_name, sig_val, sig_unit = _derive_signal(
        row_idx, duration, src_bytes, wrong_fragment,
        urgent, count, rerror_rate, dst_host_count, dst_host_srv_cnt,
    )

    return {
        "scenario_id": SCENARIO_ID,
        "emitted_at":  ts,
        "provenance":  {**_PROVENANCE, "origin_record_id": f"KDDTrain+_20Percent.txt row {row_idx}"},
        # _meta is stripped by the runner before calling pipeline.ingest()
        "_meta": {
            "klass":      klass,
            "hypothesis": HYPOTHESIS_MAP.get(klass, ""),
            "dataset":    "NSL-KDD",
            "src_bytes":  src_bytes,
            "count":      count,
        },

        "payload": {
            "sample_id":   sample_id,
            "observed_at": ts,
            "metric":      sig_name,
            "value":       sig_val,
            "unit":        sig_unit,
            "labels": {
                "entity_id": entity_id,
                "service":   service,
            },
        },
    }


class NslKddReader(DatasetReader):
    """
    Yields PrometheusAdapter-compatible raw dicts from NSL-KDD 20% training set.

    Usage::

        reader = NslKddReader()
        for raw in reader.records(data_root, limit=500):
            result = pipeline.ingest(source=reader.source_name, raw=raw, ...)
    """

    source_name   = "simulator.prometheus"
    default_limit = 1000   # safe default; full 20% sample ~25k rows

    def records(
        self,
        data_root: Path,
        *,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Yield one raw dict per NSL-KDD row, applying all derivation rules.

        Each yielded dict has a ``_meta`` key containing dataset-level metadata
        (class label, hypothesis type). The runner strips ``_meta`` before
        passing the dict to the pipeline.
        """
        path = data_root / _ARFF_TXT
        if not path.exists():
            raise FileNotFoundError(
                f"NSL-KDD dataset not found at {path}. "
                "Download KDDTrain+_20Percent.txt from https://www.unb.ca/cic/datasets/nsl.html"
            )

        effective_limit = self._effective_limit(limit)
        yielded = 0

        with path.open(encoding="latin-1") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                cols = line.split(",")
                record = _parse_row(yielded, cols)
                if record is not None:
                    yield record
                    yielded += 1
                    if effective_limit is not None and yielded >= effective_limit:
                        break


__all__ = ["NslKddReader"]
