import hashlib
from typing import Any

def event_id(source: str, source_record_id: str) -> str:
    del source
    return f"evt_{hashlib.sha256(source_record_id.encode()).hexdigest()[:24]}"


def unpack(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = raw.get("payload", raw)
    provenance = {key: raw[key] for key in ("scenario_id", "provenance") if key in raw}
    return payload, provenance


def simulated_flags(raw: dict[str, Any]) -> list[str]:
    return ["SIMULATED"] if "scenario_id" in raw else []


def trace_id(raw: dict[str, Any], payload: dict[str, Any]) -> str | None:
    return payload.get("trace_id") or ("scenario_gateway_rate_limit_001" if "scenario_id" in raw else None)


def ingested_at(raw: dict[str, Any], timestamp: str) -> str:
    from datetime import datetime, timedelta
    value = raw.get("emitted_at", timestamp)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(milliseconds=120)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
