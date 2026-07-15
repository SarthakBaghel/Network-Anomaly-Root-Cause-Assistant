"""
GAIA Dataset Bridge Reader
===========================
Reads the MicroSS anomaly injection records from GAIA's run.zip
(the ONLY extractable data — metric/trace/business are multi-part
split zips requiring 7-zip assembly).

Source: data/GAIA-DataSet-main/GAIA-DataSet-main/MicroSS/run/run.zip
Files: run_table_2021-07.csv, run_table_2021-08.csv
Schema: datetime | service | message
  - datetime: "YYYY-MM-DD" (date only)
  - service:  e.g. "dbservice1", "apiservice", "logservice"
  - message:  pipe-delimited syslog-style record containing the
              anomaly type, start time, duration, and severity

Anomaly types identified in the run data:
  - [memory_anomalies]     → resource saturation (metric modality)
  - [normal memory freed label]  → clearance marker (context_only)
  - [cpu_anomalies]        → resource saturation
  - [network_anomalies]    → network latency injection
  - [disk_anomalies]       → disk saturation
  - WARNING|ERROR|CRITICAL → log-level severity mapping

Canonical mapping:
  - memory/cpu/disk anomalies → modality=metric, event_type=RESOURCE_SATURATION
  - network anomalies         → modality=metric, event_type=NETWORK_LATENCY_SPIKE  
  - normal/freed labels       → modality=log,    event_type=CLEARANCE, context_only
  - WARNING                   → severity=0.65
  - ERROR                     → severity=0.80
  - CRITICAL                  → severity=0.95
"""

from __future__ import annotations

import csv
import io
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Iterator

# Regex to extract the structured log parts from message field
_LOG_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})[,\.]?\d*\s*\|\s*"
    r"(WARNING|ERROR|CRITICAL|INFO)\s*\|"
    r"\s*([\d\.]+)\s*\|"          # host_ip
    r"\s*([\d\.]+)\s*\|"          # container_ip
    r"\s*(\S+)\s*\|"              # service (redundant)
    r"\s*\[([^\]]+)\]"            # [anomaly_type]
    r"\s*(.*)"                    # rest of message
)

_ANOMALY_TYPE_MAP = {
    "memory_anomalies":       ("metric", "RESOURCE_SATURATION",     "memory_usage_percent"),
    "cpu_anomalies":          ("metric", "RESOURCE_SATURATION",     "cpu_usage_percent"),
    "disk_anomalies":         ("metric", "RESOURCE_SATURATION",     "disk_usage_percent"),
    "network_anomalies":      ("metric", "NETWORK_LATENCY_SPIKE",   "network_latency_ms"),
    "normal memory freed label": ("log", "CLEARANCE",               None),
    "normal cpu freed label":    ("log", "CLEARANCE",               None),
    "normal disk freed label":   ("log", "CLEARANCE",               None),
    "normal network freed label":("log", "CLEARANCE",               None),
}

_LEVEL_SEVERITY = {
    "WARNING":  0.65,
    "ERROR":    0.80,
    "CRITICAL": 0.95,
    "INFO":     0.10,
}

# GAIA MicroSS services → map to our topology entity IDs
# (best-effort: gateway/api services → api-gateway-01, db services → payment-db-01)
_SERVICE_MAP = {
    "apiservice":      "api-gateway-01",
    "apiservice1":     "api-gateway-01",
    "apiservice2":     "checkout-api-01",
    "dbservice":       "payment-db-01",
    "dbservice1":      "payment-db-01",
    "dbservice2":      "payment-db-01",
    "logservice":      "payment-api-01",
    "logservice1":     "payment-api-01",
    "logservice2":     "auth-api-01",
}
_DEFAULT_ENTITY = "api-gateway-01"


def _parse_message(service: str, message: str, row_date: str) -> dict | None:
    """Parse a GAIA run record into a canonical event dict. Returns None to skip."""
    m = _LOG_RE.search(message)
    if m is None:
        # Try minimal fallback: extract log level and anomaly bracket
        level_m = re.search(r"\|\s*(WARNING|ERROR|CRITICAL|INFO)\s*\|", message)
        type_m  = re.search(r"\[([^\]]+)\]", message)
        if not level_m or not type_m:
            return None
        level     = level_m.group(1)
        anom_tag  = type_m.group(1).lower()
        timestamp = f"{row_date}T00:00:00+00:00"
        host_ip   = None
    else:
        timestamp = m.group(1).replace(" ", "T") + "+00:00"
        level     = m.group(2)
        host_ip   = m.group(3)
        anom_tag  = m.group(6).lower()

    mapping = _ANOMALY_TYPE_MAP.get(anom_tag)
    if mapping is None:
        return None  # Unknown anomaly tag

    modality, event_type, signal_name = mapping
    severity  = _LEVEL_SEVERITY.get(level, 0.5)
    entity_id = _SERVICE_MAP.get(service.lower(), _DEFAULT_ENTITY)

    record: dict = {
        "event_id":          f"gaia_{uuid.uuid4().hex[:16]}",
        "timestamp":         timestamp,
        "entity_id":         entity_id,
        "modality":          modality,
        "event_type":        event_type,
        "severity":          severity,
        "source":            "gaia.run",
        "trace_or_session_id": None,
        "raw_payload": {
            "gaia_service": service,
            "gaia_anom_tag": anom_tag,
            "gaia_host_ip": host_ip,
            "gaia_level": level,
        },
    }
    if signal_name:
        # Extract numeric value from message if present (e.g. "use 1g memory")
        val_m = re.search(r"use\s+(\d+)([gGmM]?)\s*(memory|cpu|disk)", message, re.I)
        if val_m:
            val = float(val_m.group(1))
            unit_suffix = val_m.group(2).lower()
            if unit_suffix == "g":
                val *= 1024  # convert GB → MB equivalent
        else:
            val = severity * 100.0  # fallback: severity × 100 as usage %

        record["signal_name"]  = signal_name
        record["signal_value"] = val
        record["unit"]         = "percent" if "usage" in signal_name else "ms"

    # Mark clearance records as context_only
    if event_type == "CLEARANCE":
        record["_meta"] = {"context_only": True}

    return record


class GaiaRunReader:
    """Reads GAIA MicroSS anomaly injection records from run.zip."""

    source_name = "gaia.run"

    def records(
        self,
        data_root: Path,
        *,
        limit: int | None = 500,
        months: list[str] | None = None,
        **_kwargs,
    ) -> list[dict]:
        """
        Yield canonical event dicts from GAIA run.zip.

        Args:
            data_root: Repository data/ directory.
            limit:     Max records to return (None = all).
            months:    List of month suffixes to include, e.g. ["2021-07"].
                       Default: both months.
        """
        zip_path = (
            data_root
            / "GAIA-DataSet-main"
            / "GAIA-DataSet-main"
            / "MicroSS"
            / "run"
            / "run.zip"
        )
        if not zip_path.exists():
            raise FileNotFoundError(f"GAIA run.zip not found at: {zip_path}")

        include_months = set(months) if months else {"2021-07", "2021-08"}
        results: list[dict] = []

        with zipfile.ZipFile(zip_path, "r") as zf:
            for entry in zf.namelist():
                if not entry.endswith(".csv"):
                    continue
                # Filter by requested months
                month_match = re.search(r"(\d{4}-\d{2})", entry)
                if month_match and month_match.group(1) not in include_months:
                    continue

                with zf.open(entry) as f:
                    text    = f.read().decode("utf-8", errors="replace")
                    reader  = csv.DictReader(io.StringIO(text))
                    for row in reader:
                        if limit and len(results) >= limit:
                            return results
                        service = (row.get("service") or "").strip()
                        message = (row.get("message") or "").strip()
                        row_date = (row.get("datetime") or "2021-07-01").strip()
                        if not message:
                            continue
                        parsed = _parse_message(service, message, row_date)
                        if parsed is not None:
                            results.append(parsed)

        return results


__all__ = ["GaiaRunReader"]
