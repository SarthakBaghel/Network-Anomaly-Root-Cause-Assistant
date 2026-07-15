"""
UNSW-NB15 Dataset Reader
=========================
Reads UNSW_NB15_training-set.parquet and maps each row to the
PrometheusAdapter payload schema using the derivation rules from
DatasetDescription.md §2 (synthetic columns).

PrometheusAdapter payload schema (required fields):
    payload.sample_id    <- "unsw-train-{id:06d}"
    payload.observed_at  <- BASE_TIMESTAMP + row_index * 10s  (ISO-8601 UTC)
    payload.metric       <- one of the 4 derived signal names
    payload.value        <- float derived from UNSW-NB15 columns
    payload.unit         <- per-signal unit string
    payload.labels.entity_id <- SERVICE_TO_ENTITY[service_column]

Derivation rules (DatasetDescription.md §2):
    checkout_p95_latency_ms   = sinpkt * 15          [clip 0..5000 ms]
    active_connections_total  = ct_src_ltm            (direct, connection window count)
    tcp_resets_total          = sloss                 (source packets dropped/retransmitted)
    db_connection_utilization = sloss / max(spkts, 1) (packet loss ratio as utilization proxy)

Attack -> hypothesis vocabulary (used for provenance only):
    DoS / Generic / Fuzzers / Worms  -> dos_or_traffic_surge
    Exploits / Backdoors / Shellcode -> configuration_regression
    Reconnaissance / Analysis        -> external_probe

Critical rule (DatasetDescription.md §2):
    attack_cat and label columns must NEVER be written into
    network_profile.json or any runtime fixture (§3.3 target-leakage rule).
    They appear here only to populate _meta for offline analysis.
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

# File paths relative to data_root
_TRAIN_PARQUET = "unsw_nb15/UNSW_NB15_training-set.parquet"
_TEST_PARQUET  = "unsw_nb15/UNSW_NB15_testing-set.parquet"

# Ordered list of (signal_name, unit) — rotated round-robin across rows
_SIGNALS: list[tuple[str, str]] = [
    ("checkout_p95_latency_ms",     "ms"),
    ("active_connections_total",    "connections"),
    ("tcp_resets_total",            "count/10s"),
    ("db_connection_utilization",   "ratio"),
]

_PROVENANCE = make_provenance(
    origin="UNSW-NB15",
    origin_record_id="UNSW_NB15_training-set.parquet",
    license_reference="CC-BY-4.0",
    synthetic_fields=[
        "sample_id", "observed_at", "metric", "value",
        "unit", "entity_id", "labels",
    ],
)


def _derive_signal(
    row_idx: int,
    sinpkt: float,
    sloss: float,
    spkts: int,
    ct_src_ltm: float,
) -> tuple[str, float, str]:
    """Return (signal_name, value, unit) for a given row index."""
    sig_name, unit = _SIGNALS[row_idx % len(_SIGNALS)]

    raw_values = {
        "checkout_p95_latency_ms":   min(sinpkt * 15.0, 5000.0),
        "active_connections_total":  ct_src_ltm,
        "tcp_resets_total":          sloss,
        "db_connection_utilization": sloss / max(spkts, 1),
    }
    return sig_name, raw_values[sig_name], unit


def _parse_row(row_idx: int, row: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one UNSW-NB15 row dict to a PrometheusAdapter raw dict."""
    try:
        service    = str(row.get("service", "-") or "-").strip()
        sinpkt     = float(row.get("sinpkt", 0)  or 0)
        sloss      = float(row.get("sloss", 0)   or 0)
        spkts      = max(int(row.get("spkts", 1) or 1), 1)
        ct_src_ltm = float(row.get("ct_src_ltm", 0) or 0)
        attack_cat = str(row.get("attack_cat", "Normal") or "Normal").strip()
        label      = int(row.get("label", 0) or 0)
    except (ValueError, TypeError):
        return None

    entity_id = entity_from_service(service)
    ts        = (BASE_TIMESTAMP + timedelta(seconds=row_idx * 10)).isoformat().replace("+00:00", "Z")
    sample_id = f"unsw-train-{row_idx:06d}"

    sig_name, sig_val, sig_unit = _derive_signal(row_idx, sinpkt, sloss, spkts, ct_src_ltm)

    return {
        "scenario_id": SCENARIO_ID,
        "emitted_at":  ts,
        "provenance":  {**_PROVENANCE, "origin_record_id": f"UNSW_NB15_training-set.parquet row {row_idx}"},
        # _meta stripped by runner — never written to DB or network_profile
        "_meta": {
            "attack_cat": attack_cat,
            "label":      label,
            "hypothesis": HYPOTHESIS_MAP.get(attack_cat, ""),
            "dataset":    "UNSW-NB15",
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


class UnswNb15Reader(DatasetReader):
    """
    Yields PrometheusAdapter-compatible raw dicts from UNSW-NB15 training set.

    Requires ``pyarrow`` (already installed in the project venv).

    Usage::

        reader = UnswNb15Reader()
        for raw in reader.records(data_root, limit=500):
            result = pipeline.ingest(source=reader.source_name, raw=raw, ...)
    """

    source_name   = "simulator.prometheus"
    default_limit = 1000

    def records(
        self,
        data_root: Path,
        *,
        limit: int | None = None,
        split: str = "train",   # "train" | "test"
    ) -> Iterator[dict[str, Any]]:
        """
        Yield one raw dict per UNSW-NB15 row.

        Args:
            data_root: Absolute path to the project ``data/`` directory.
            limit:     Max rows to yield (None = use default_limit).
            split:     ``"train"`` (default) or ``"test"`` parquet file.
        """
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("pandas is required for UNSW-NB15 ingestion") from exc

        filename = _TRAIN_PARQUET if split == "train" else _TEST_PARQUET
        path     = data_root / filename
        if not path.exists():
            raise FileNotFoundError(
                f"UNSW-NB15 dataset not found at {path}. "
                "Download from https://research.unsw.edu.au/projects/unsw-nb15-dataset"
            )

        effective_limit = self._effective_limit(limit)
        df = pd.read_parquet(path)
        if effective_limit is not None:
            df = df.head(effective_limit)

        for row_idx, row_dict in enumerate(df.to_dict("records")):
            record = _parse_row(row_idx, row_dict)
            if record is not None:
                yield record


__all__ = ["UnswNb15Reader"]
