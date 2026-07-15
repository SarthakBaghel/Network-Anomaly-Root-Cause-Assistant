from app.contracts import CanonicalEvent
from app.ingestion.adapters.base import AdapterError
from app.ingestion.adapters.common import event_id, ingested_at, simulated_flags, trace_id, unpack
from app.ingestion.catalogue import alert_severity


class AlertmanagerAdapter:
    source_name = "simulator.alertmanager"

    def adapt(self, raw: dict) -> CanonicalEvent:
        payload, metadata = unpack(raw)
        try:
            record_id, timestamp, labels = payload["fingerprint"], payload["startsAt"], payload["labels"]
            entity, name = labels["entity_id"], labels["alertname"]
        except (KeyError, TypeError) as exc:
            raise AdapterError("ALERTMANAGER_MAPPING_ERROR", f"missing field: {exc}") from exc
        severity = alert_severity(str(labels.get("severity", "warning")))
        event_type = {"HighForwardedRequestAndConnectionRate": "HIGH_FORWARDED_REQUEST_AND_CONNECTION_RATE", "HighCheckoutErrorRate": "HIGH_CHECKOUT_ERROR_RATE"}.get(name, name.upper())
        return CanonicalEvent(event_id=event_id(self.source_name, record_id), timestamp=timestamp, ingested_at=ingested_at(raw, timestamp), entity_id=entity, modality="alert", event_type=event_type, severity=severity, trace_or_session_id=trace_id(raw, payload), source=self.source_name, source_record_id=record_id, schema_version="1.0", quality_flags=simulated_flags(raw), raw_payload={**payload, **metadata})
