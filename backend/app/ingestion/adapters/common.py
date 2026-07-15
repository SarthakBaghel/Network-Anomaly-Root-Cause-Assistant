import hashlib
from datetime import datetime, timezone
from typing import Any

import ulid

from app.config import settings


def event_id(
    source: str,
    source_record_id: str,
    timestamp: str | datetime,
    raw: dict[str, Any] | None = None,
) -> str:
    """Return a deterministic, time-sortable event ID.

    The timestamp supplies the ULID time component and a SHA-256 digest of the
    configured seed, source identity, and source record ID supplies its entropy.
    Including the source avoids collisions when two adapters use the same native
    record identifier.
    """

    if isinstance(timestamp, str):
        observed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    else:
        observed_at = timestamp
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    observed_at = observed_at.astimezone(timezone.utc)
    timestamp_ms = int(observed_at.timestamp() * 1000)
    if not 0 <= timestamp_ms < 2**48:
        raise ValueError("event timestamp is outside the ULID range")

    provenance = (raw or {}).get("provenance", {})
    seed = provenance.get("seed", settings.simulator_seed) if isinstance(provenance, dict) else settings.simulator_seed
    entropy = hashlib.sha256(
        f"{seed}|{source}|{source_record_id}".encode("utf-8")
    ).digest()[:10]
    value = timestamp_ms.to_bytes(6, "big") + entropy
    return f"evt_{ulid.from_bytes(value).str.lower()}"


def unpack(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = raw.get("payload", raw)
    provenance = {key: raw[key] for key in ("scenario_id", "provenance") if key in raw}
    return payload, provenance


def simulated_flags(raw: dict[str, Any]) -> list[str]:
    return ["SIMULATED"] if "scenario_id" in raw else []


def trace_id(raw: dict[str, Any], payload: dict[str, Any]) -> str | None:
    explicit = payload.get("trace_id")
    if explicit:
        return str(explicit)
    scenario_id = raw.get("scenario_id")
    return str(scenario_id) if scenario_id else None


def ingested_at(raw: dict[str, Any], timestamp: str) -> str:
    from datetime import datetime, timedelta
    value = raw.get("emitted_at", timestamp)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(milliseconds=120)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
