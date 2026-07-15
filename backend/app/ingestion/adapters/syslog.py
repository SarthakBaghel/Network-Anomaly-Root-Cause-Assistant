from app.contracts import CanonicalEvent
from app.ingestion.adapters.base import AdapterError
from app.ingestion.adapters.common import event_id, ingested_at, simulated_flags, trace_id, unpack
from app.ingestion.catalogue import log_rule

LEVEL_SEVERITY = {"debug": 0.1, "info": 0.2, "notice": 0.3, "warning": 0.5, "error": 0.8, "critical": 0.95, "fatal": 1.0}


class SyslogAdapter:
    source_name = "simulator.syslog"

    def adapt(self, raw: dict) -> CanonicalEvent:
        payload, metadata = unpack(raw)
        try:
            record_id, timestamp, entity, code = payload["record_id"], payload["observed_at"], payload["host"], payload["code"]
        except KeyError as exc:
            raise AdapterError("SYSLOG_MAPPING_ERROR", f"missing field: {exc}") from exc
        rule = log_rule(code)
        severity = float(rule["normalized_severity"]) if rule else LEVEL_SEVERITY.get(str(payload.get("level", "warning")).lower(), 0.5)
        return CanonicalEvent(event_id=event_id(self.source_name, record_id, timestamp, raw), timestamp=timestamp, ingested_at=ingested_at(raw, timestamp), entity_id=entity, modality="log", event_type=code, severity=severity, trace_or_session_id=trace_id(raw, payload), source=self.source_name, source_record_id=record_id, schema_version="1.0", quality_flags=simulated_flags(raw), raw_payload={**payload, **metadata})
