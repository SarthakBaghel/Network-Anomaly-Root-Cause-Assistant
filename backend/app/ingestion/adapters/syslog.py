from app.contracts import CanonicalEvent
from app.ingestion.adapters.base import AdapterError
from app.ingestion.adapters.common import event_id, ingested_at, simulated_flags, trace_id, unpack

SEVERITY = {"HEALTH_CHECK_OK": 0.2, "UPSTREAM_CONNECTION_TIMEOUT": 0.8, "CERTIFICATE_EXPIRY_WARNING": 0.35}


class SyslogAdapter:
    source_name = "simulator.syslog"

    def adapt(self, raw: dict) -> CanonicalEvent:
        payload, metadata = unpack(raw)
        try:
            record_id, timestamp, entity, code = payload["record_id"], payload["observed_at"], payload["host"], payload["code"]
        except KeyError as exc:
            raise AdapterError("SYSLOG_MAPPING_ERROR", f"missing field: {exc}") from exc
        return CanonicalEvent(event_id=event_id(self.source_name, record_id), timestamp=timestamp, ingested_at=ingested_at(raw, timestamp), entity_id=entity, modality="log", event_type=code, severity=SEVERITY.get(code, 0.5), trace_or_session_id=trace_id(raw, payload), source=self.source_name, source_record_id=record_id, schema_version="1.0", quality_flags=simulated_flags(raw), raw_payload={**payload, **metadata})
