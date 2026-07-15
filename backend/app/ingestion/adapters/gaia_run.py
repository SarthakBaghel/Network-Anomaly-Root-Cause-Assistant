"""
GaiaRunAdapter — pass-through adapter for GAIA MicroSS anomaly injection records.

The GaiaRunReader already produces canonical-shaped dicts (the GAIA dataset
has pre-formed timestamps, entity IDs, modality, event_type, and severity).
This adapter validates and promotes those fields into a CanonicalEvent.

Source name: gaia.run
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.contracts import CanonicalEvent, Modality
from app.ingestion.adapters.base import AdapterError


_ALLOWED_MODALITIES = {m.value for m in Modality}

_ALLOWED_EVENT_TYPES = {
    "RESOURCE_SATURATION",
    "NETWORK_LATENCY_SPIKE",
    "CLEARANCE",
    "UPSTREAM_CONNECTION_TIMEOUT",
    "UPSTREAM_TIMEOUT",
    "CONN_REFUSED",
    "ANOMALY_INJECTION",
}


class GaiaRunAdapter:
    """Adapt pre-formed GAIA run records into CanonicalEvent.

    The GaiaRunReader builds dicts with the canonical field shape.
    This adapter validates required fields and constructs the contract object.
    """

    source_name = "gaia.run"

    def adapt(self, raw: dict) -> CanonicalEvent:
        # Required fields
        try:
            event_id_raw  = str(raw["event_id"])
            timestamp_raw = raw["timestamp"]
            entity_id     = str(raw["entity_id"])
            modality_raw  = str(raw["modality"])
            event_type    = str(raw["event_type"])
            severity      = float(raw.get("severity", 0.5))
        except KeyError as exc:
            raise AdapterError("GAIA_MISSING_FIELD", f"required field missing: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise AdapterError("GAIA_FIELD_TYPE_ERROR", f"field type error: {exc}") from exc

        # Validate modality
        if modality_raw not in _ALLOWED_MODALITIES:
            raise AdapterError(
                "GAIA_INVALID_MODALITY",
                f"modality '{modality_raw}' not in allowed set {_ALLOWED_MODALITIES}",
            )

        # Normalise timestamp
        if isinstance(timestamp_raw, datetime):
            ts = timestamp_raw
        else:
            try:
                ts = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
            except ValueError as exc:
                raise AdapterError("GAIA_BAD_TIMESTAMP", f"bad timestamp: {timestamp_raw}") from exc

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        return CanonicalEvent(
            event_id=event_id_raw,
            timestamp=ts,
            ingested_at=datetime.now(tz=timezone.utc),
            entity_id=entity_id,
            modality=Modality(modality_raw),
            event_type=event_type,
            severity=min(max(severity, 0.0), 1.0),
            signal_name=raw.get("signal_name"),
            signal_value=raw.get("signal_value"),
            unit=raw.get("unit"),
            trace_or_session_id=raw.get("trace_or_session_id"),
            source=self.source_name,
            source_record_id=event_id_raw,
            schema_version="1.0",
            quality_flags=["REFERENCE_DERIVED"],
            raw_payload=dict(raw.get("raw_payload") or {}),
        )
