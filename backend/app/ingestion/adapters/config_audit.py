from app.contracts import CanonicalEvent
from app.ingestion.adapters.base import AdapterError
from app.ingestion.adapters.common import event_id, ingested_at, simulated_flags, trace_id, unpack


class ConfigAuditAdapter:
    source_name = "simulator.config_audit"

    def adapt(self, raw: dict) -> CanonicalEvent:
        payload, metadata = unpack(raw)
        try:
            record_id, timestamp, entity = payload["change_id"], payload["changed_at"], payload["target_entity_id"]
        except KeyError as exc:
            raise AdapterError("CONFIG_AUDIT_MAPPING_ERROR", f"missing field: {exc}") from exc
        return CanonicalEvent(event_id=event_id(self.source_name, record_id), timestamp=timestamp, ingested_at=ingested_at(raw, timestamp), entity_id=entity, modality="config_change", event_type="CONFIG_VALUE_CHANGED", severity=0, trace_or_session_id=trace_id(raw, payload), source=self.source_name, source_record_id=record_id, schema_version="1.0", quality_flags=simulated_flags(raw), raw_payload={**payload, **metadata, "context_only": True})
