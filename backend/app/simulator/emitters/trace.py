from datetime import datetime

from app.simulator.emitters.base import BaseEmitter, iso_utc


class TraceEmitter(BaseEmitter):
    source_name = "simulator.trace"

    def emit(
        self,
        *,
        span_id: str,
        observed_at: datetime,
        entity_id: str,
        trace_id: str,
        parent_span_id: str | None,
        operation: str,
        duration_ms: float,
        expected_p99_ms: float,
        status: str,
        scenario_id: str,
        peer_service: str | None = None,
        provenance: dict | None = None,
    ) -> dict:
        payload = {
            "record_id": span_id,
            "span_id": span_id,
            "observed_at": iso_utc(observed_at),
            "entity_id": entity_id,
            "trace_id": trace_id,
            "parent_span_id": parent_span_id,
            "operation": operation,
            "duration_ms": duration_ms,
            "expected_p99_ms": expected_p99_ms,
            "status": status,
            "peer_service": peer_service,
        }
        return self.envelope(payload, scenario_id, observed_at, provenance)
