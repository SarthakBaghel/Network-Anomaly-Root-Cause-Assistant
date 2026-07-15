from app.contracts import CanonicalEvent
from app.ingestion.adapters.base import AdapterError
from app.ingestion.adapters.common import event_id, ingested_at, simulated_flags, trace_id, unpack

EVENT_TYPES = {
    "raw_ingress_requests_per_second": "RAW_INGRESS_RATE",
    "forwarded_requests_per_second": "FORWARDED_REQUEST_RATE",
    "active_connections_total": "ACTIVE_CONNECTIONS",
    "connection_utilization": "CONNECTION_UTILIZATION",
    "tcp_resets_total": "TCP_RESETS",
    "tcp_retransmissions_total": "TCP_RETRANSMISSIONS",
    "checkout_p95_latency_ms": "CHECKOUT_P95_LATENCY",
    "db_connection_utilization": "DB_CONNECTION_UTILIZATION",
    "packet_loss_rate": "PACKET_LOSS_RATE",
    "network_latency_ms": "NETWORK_LATENCY",
    "syn_error_rate": "SYN_ERROR_RATE",
    "source_distribution_change_score": "SOURCE_DISTRIBUTION_CHANGE_SCORE",
    "cpu_usage_percent": "CPU_USAGE_PERCENT",
    "memory_usage_percent": "MEMORY_USAGE_PERCENT",
    "service_p95_latency_ms": "SERVICE_P95_LATENCY",
    "unique_destination_ports": "UNIQUE_DESTINATION_PORTS",
    "rejected_connection_rate": "REJECTED_CONNECTION_RATE",
    "destination_fanout": "DESTINATION_FANOUT",
    "datanode_io_error_rate": "DATANODE_IO_ERROR_RATE",
}


class PrometheusAdapter:
    source_name = "simulator.prometheus"

    def adapt(self, raw: dict) -> CanonicalEvent:
        payload, metadata = unpack(raw)
        try:
            record_id, timestamp = payload["sample_id"], payload["observed_at"]
            metric, value, unit = payload["metric"], payload["value"], payload["unit"]
            entity = payload["labels"]["entity_id"]
        except (KeyError, TypeError) as exc:
            raise AdapterError("PROMETHEUS_MAPPING_ERROR", f"missing field: {exc}") from exc
        return CanonicalEvent(
            event_id=event_id(self.source_name, record_id, timestamp, raw),
            timestamp=timestamp,
            ingested_at=ingested_at(raw, timestamp),
            entity_id=entity,
            modality="metric",
            event_type=EVENT_TYPES.get(metric, metric.upper()),
            severity=0,
            signal_name=metric,
            signal_value=value,
            unit=unit,
            trace_or_session_id=trace_id(raw, payload),
            source=self.source_name,
            source_record_id=record_id,
            schema_version="1.0",
            quality_flags=simulated_flags(raw),
            raw_payload={**payload, **metadata},
        )
