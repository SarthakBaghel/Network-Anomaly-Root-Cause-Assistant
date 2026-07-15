"""
Loghub HDFS Dataset Reader
===========================
Reads HDFS.log (1.5 GB raw log file) and maps each parseable line to the
SyslogAdapter payload schema using the derivation rules from
DatasetDescription.md §3 (synthetic columns).

SyslogAdapter payload schema (required fields):
    payload.record_id    <- "hdfs-{line_index:08d}"
    payload.observed_at  <- parse YYMMDD HHMMSS -> ISO-8601 UTC
    payload.host         <- IP prefix -> entity_id  (or DEFAULT_ENTITY_ID)
    payload.code         <- component+message pattern -> event code

Optional syslog fields also populated:
    payload.level        <- normalised level string ("info", "warning", "error", "fatal")
    payload.message      <- raw message text (truncated to 200 chars)
    payload.facility     <- "application" (constant)
    payload.trace_id     <- blk_{block_id} extracted from message
    payload.attributes   <- {"component": ..., "thread_id": ..., "hdfs_block": ...}

Derivation rules (DatasetDescription.md §3):
    record_id   = "hdfs-{line_index:08d}"
    timestamp   = parse YYMMDD HHMMSS -> datetime UTC (year prefix = 2000+YY)
    host        = extract /10.x.x.x: IP from message -> IP_PREFIX_TO_ENTITY map
    facility    = "application" (constant for all HDFS logs)
    code        = first matching HDFS_CODE_MAP pattern in message text
    template_id = assigned per code -> detector_rules.yaml log_rules
    trace_id    = extract blk_{id} from message as session identifier
    attributes  = {block_id, src_ip, component, thread_id}

Key log template mappings (from DatasetDescription.md §3):
    "Receiving block"  -> BLOCK_RECEIVE
    "addStoredBlock"   -> BLOCK_STORED
    "PacketResponder"  -> PACKET_RESPONDER_TERMINATE
    "Unexpected error" -> BLOCK_NOT_FOUND
    "Received block"   -> BLOCK_RECEIVED
    "timed out"        -> UPSTREAM_CONNECTION_TIMEOUT
    "Exception"        -> UPSTREAM_CONNECTION_TIMEOUT
    "failed"           -> DNS_RESOLUTION_FAILED
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .base import (
    BASE_TIMESTAMP,
    DEFAULT_ENTITY_ID,
    SCENARIO_ID,
    DatasetReader,
    make_provenance,
)

# File path relative to data_root
_HDFS_LOG = "loghub/HDFS/HDFS.log"

# DatasetDescription.md §3: IP prefix -> frozen entity_id
_IP_PREFIX_TO_ENTITY: dict[str, str] = {
    "10.250.19": "api-gateway-01",
    "10.250.10": "payment-api-01",
    "10.250.11": "checkout-api-01",
    "10.250.12": "auth-api-01",
    "10.250.13": "payment-db-01",
}

# Ordered message pattern -> event code (first match wins)
# Matches DatasetDescription.md §3 key log templates
_CODE_MAP: list[tuple[str, str]] = [
    ("Receiving block",  "BLOCK_RECEIVE"),
    ("addStoredBlock",   "BLOCK_STORED"),
    ("PacketResponder",  "PACKET_RESPONDER_TERMINATE"),
    ("Unexpected error", "BLOCK_NOT_FOUND"),
    ("Received block",   "BLOCK_RECEIVED"),
    ("timed out",        "UPSTREAM_CONNECTION_TIMEOUT"),
    ("Exception",        "UPSTREAM_CONNECTION_TIMEOUT"),
    ("timeout",          "UPSTREAM_CONNECTION_TIMEOUT"),
    ("connection pool",  "CONNECTION_POOL_PRESSURE"),
    ("failed",           "DNS_RESOLUTION_FAILED"),
    ("WARN",             "PACKET_LOSS_WARNING"),
]

_LEVEL_MAP: dict[str, str] = {
    "INFO": "info", "WARN": "warning", "WARNING": "warning",
    "ERROR": "error", "FATAL": "fatal",
}

# HDFS log line regex: YYMMDD HHMMSS <thread_id> <LEVEL> <Component>: <message>
_LINE_RE = re.compile(
    r"^(\d{6})\s+(\d{6})\s+(\d+)\s+(\w+)\s+([^:]+):\s*(.*)$"
)
_IP_RE  = re.compile(r"/(10\.\d+\.\d+)\.\d+")
_BLK_RE = re.compile(r"(blk_-?\d+)")

_PROVENANCE = make_provenance(
    origin="Loghub-HDFS",
    origin_record_id="HDFS.log",
    license_reference="CC-BY-4.0",
    synthetic_fields=[
        "record_id", "observed_at", "host", "code", "trace_id", "attributes",
    ],
)


def _parse_timestamp(date_s: str, time_s: str) -> str:
    """Parse YYMMDD HHMMSS into ISO-8601 UTC string."""
    try:
        year   = 2000 + int(date_s[:2])
        month  = int(date_s[2:4])
        day    = int(date_s[4:6])
        hour   = int(time_s[:2])
        minute = int(time_s[2:4])
        sec    = int(time_s[4:6])
        return (
            datetime(year, month, day, hour, minute, sec, tzinfo=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (ValueError, OverflowError):
        return None


def _entity_from_message(message: str) -> str:
    """Extract IP prefix from HDFS message and map to frozen entity_id."""
    m = _IP_RE.search(message)
    if m:
        return _IP_PREFIX_TO_ENTITY.get(m.group(1), DEFAULT_ENTITY_ID)
    return DEFAULT_ENTITY_ID


def _code_from_message(message: str, component: str) -> str:
    """Map HDFS message text to a canonical event code."""
    combined = message + " " + component
    for pattern, code in _CODE_MAP:
        if pattern in combined:
            return code
    return "HEALTH_CHECK_OK"


def _parse_line(line_idx: int, line: str) -> dict[str, Any] | None:
    """
    Parse one HDFS log line into a SyslogAdapter raw dict.
    Returns None if the line does not match the expected format.
    """
    m = _LINE_RE.match(line.strip())
    if not m:
        return None

    date_s, time_s, tid, level_raw, component, message = m.groups()

    ts = _parse_timestamp(date_s, time_s)
    if ts is None:
        # Fallback: synthesise a timestamp from the base timestamp
        ts = (BASE_TIMESTAMP + timedelta(seconds=line_idx * 5)).isoformat().replace("+00:00", "Z")

    entity_id  = _entity_from_message(message)
    code       = _code_from_message(message, component)
    level      = _LEVEL_MAP.get(level_raw.upper(), "info")
    record_id  = f"hdfs-{line_idx:08d}"

    blk_m      = _BLK_RE.search(message)
    trace_id   = blk_m.group(1) if blk_m else f"hdfs-thread-{tid}"

    ip_m = _IP_RE.search(message)

    return {
        "scenario_id": SCENARIO_ID,
        "emitted_at":  ts,
        "provenance":  {**_PROVENANCE, "origin_record_id": f"HDFS.log line {line_idx}"},
        "_meta": {
            "raw_level": level_raw,
            "component": component.strip(),
            "dataset":   "Loghub-HDFS",
        },
        "payload": {
            "record_id":   record_id,
            "observed_at": ts,
            "host":        entity_id,
            "code":        code,
            "level":       level,
            "message":     message[:200],
            "facility":    "application",
            "trace_id":    trace_id,
            "attributes": {
                "component":  component.strip(),
                "thread_id":  tid,
                "hdfs_block": blk_m.group(1) if blk_m else None,
                "src_ip":     ip_m.group(0).lstrip("/") if ip_m else None,
            },
        },
    }


class LoghubHdfsReader(DatasetReader):
    """
    Yields SyslogAdapter-compatible raw dicts from the Loghub HDFS log.

    The HDFS.log is 1.5 GB (~11M lines). Use ``limit`` to control how
    many lines are read in a single session. The default is 1000 lines
    for safety.

    Usage::

        reader = LoghubHdfsReader()
        for raw in reader.records(data_root, limit=500):
            result = pipeline.ingest(source=reader.source_name, raw=raw, ...)
    """

    source_name   = "simulator.syslog"
    default_limit = 1000   # 1000 lines; set limit=0 to stream all 11M

    def records(
        self,
        data_root: Path,
        *,
        limit: int | None = None,
        skip_lines: int = 0,   # start reading from this line (resumable)
    ) -> Iterator[dict[str, Any]]:
        """
        Yield one raw dict per parseable HDFS log line.

        Args:
            data_root:   Absolute path to the project ``data/`` directory.
            limit:       Max records to yield. Defaults to ``default_limit``.
            skip_lines:  Skip this many lines before starting (enables chunked reads).
        """
        path = data_root / _HDFS_LOG
        if not path.exists():
            raise FileNotFoundError(
                f"Loghub HDFS log not found at {path}. "
                "This file is 1.5 GB and is not committed to the repo — "
                "see data/loghub/HDFS/ for download instructions."
            )

        effective_limit = self._effective_limit(limit)
        yielded     = 0
        line_global = 0

        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line_global += 1
                if skip_lines > 0 and line_global <= skip_lines:
                    continue
                record = _parse_line(line_global - 1, line)
                if record is not None:
                    yield record
                    yielded += 1
                    if effective_limit is not None and yielded >= effective_limit:
                        break


__all__ = ["LoghubHdfsReader"]
