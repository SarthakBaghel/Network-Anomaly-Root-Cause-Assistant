from app.contracts import CanonicalEvent
from app.ingestion.adapters.base import AdapterError
from app.ingestion.adapters.common import event_id, ingested_at, simulated_flags, unpack


class TraceAdapter:
    source_name = "simulator.trace"

    def adapt(self, raw: dict) -> CanonicalEvent:
        payload, metadata = unpack(raw)
        try:
            record_id = str(payload["record_id"])
            timestamp = payload["observed_at"]
            entity_id = str(payload["entity_id"])
            trace_id = str(payload["trace_id"])
            duration_ms = float(payload["duration_ms"])
            expected_p99_ms = float(payload["expected_p99_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterError("TRACE_MAPPING_ERROR", f"invalid or missing field: {exc}") from exc
        if duration_ms < 0 or expected_p99_ms <= 0:
            raise AdapterError(
                "TRACE_MAPPING_ERROR",
                "trace durations must be non-negative with a positive baseline",
            )
        status = str(payload.get("status", "ok")).lower()
        severity = 0.8 if status in {"error", "failed"} else 0.0
        return CanonicalEvent(
            event_id=event_id(self.source_name, record_id, timestamp, raw),
            timestamp=timestamp,
            ingested_at=ingested_at(raw, timestamp),
            entity_id=entity_id,
            modality="trace",
            event_type="TRACE_SPAN",
            severity=severity,
            signal_name="trace_span_duration_ms",
            signal_value=duration_ms,
            unit="ms",
            trace_or_session_id=trace_id,
            source=self.source_name,
            source_record_id=record_id,
            schema_version="1.0",
            quality_flags=simulated_flags(raw),
            raw_payload={**payload, **metadata},
        )
