from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from app.simulator.emitters import (
    AlertmanagerEmitter,
    PrometheusEmitter,
    SyslogEmitter,
    TraceEmitter,
)
from app.simulator.timeline import (
    SCENARIO_ID as PRIMARY_SCENARIO_ID,
    SCENARIO_KEY as PRIMARY_SCENARIO_KEY,
    TRACE_ID as PRIMARY_TRACE_ID,
    TRIGGER_TIME,
    ScheduledGroup,
    scenario_groups as primary_scenario_groups,
)


Difficulty = Literal["introductory", "intermediate", "advanced"]


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    title: str
    description: str
    affected_entity_ids: tuple[str, ...]
    duration_seconds: int
    expected_signals: tuple[str, ...]
    difficulty: Difficulty
    reference_datasets: tuple[str, ...] = ()
    transformation_version: str = "synthetic-scenario-1.0"
    quality_flag: Literal["SYNTHETIC", "REFERENCE_DERIVED"] = "SYNTHETIC"


SCENARIOS = (
    ScenarioDefinition(
        scenario_id=PRIMARY_SCENARIO_KEY,
        title="Gateway rate-limit disabled",
        description=(
            "A configuration regression disables gateway rate limiting while raw ingress "
            "remains stable, creating downstream saturation."
        ),
        affected_entity_ids=("api-gateway-01", "checkout-api-01", "payment-api-01"),
        duration_seconds=120,
        expected_signals=(
            "configuration change",
            "forwarded request spike",
            "connection pressure",
            "checkout latency",
            "upstream timeout",
        ),
        difficulty="introductory",
    ),
    ScenarioDefinition(
        scenario_id="network_path_congestion",
        title="Network-path degradation",
        description=(
            "Packet loss, TCP retransmissions, and path latency rise between the gateway "
            "and checkout service."
        ),
        affected_entity_ids=("api-gateway-01", "checkout-api-01"),
        duration_seconds=75,
        expected_signals=("packet loss", "TCP retransmissions", "path latency"),
        difficulty="advanced",
        reference_datasets=("GAIA MicroSS", "UNSW-NB15"),
        transformation_version="reference-scenario-builder-1.0",
        quality_flag="REFERENCE_DERIVED",
    ),
    ScenarioDefinition(
        scenario_id="ddos_syn_flood",
        title="DDoS / SYN flood",
        description=(
            "A sharp ingress surge, SYN error ratio, and source-distribution shift overload "
            "the gateway without a preceding configuration change."
        ),
        affected_entity_ids=("api-gateway-01", "checkout-api-01"),
        duration_seconds=90,
        expected_signals=("ingress surge", "SYN failures", "source distribution shift"),
        difficulty="advanced",
        reference_datasets=("UNSW-NB15", "NSL-KDD"),
        transformation_version="reference-scenario-builder-1.0",
        quality_flag="REFERENCE_DERIVED",
    ),
    ScenarioDefinition(
        scenario_id="gaia_resource_saturation",
        title="GAIA resource saturation",
        description=(
            "CPU and memory saturation in the payment service propagate latency to checkout."
        ),
        affected_entity_ids=("payment-api-01", "checkout-api-01"),
        duration_seconds=90,
        expected_signals=("CPU saturation", "memory saturation", "service latency"),
        difficulty="intermediate",
        reference_datasets=("GAIA MicroSS",),
        transformation_version="reference-scenario-builder-1.0",
        quality_flag="REFERENCE_DERIVED",
    ),
    ScenarioDefinition(
        scenario_id="port_scan_reconnaissance",
        title="Port scan / reconnaissance",
        description=(
            "A single source fans out across ports and destinations while connection "
            "rejections spike at the gateway."
        ),
        affected_entity_ids=("api-gateway-01",),
        duration_seconds=60,
        expected_signals=("port fanout", "connection rejection", "destination fanout"),
        difficulty="intermediate",
        reference_datasets=("UNSW-NB15", "NSL-KDD"),
        transformation_version="reference-scenario-builder-1.0",
        quality_flag="REFERENCE_DERIVED",
    ),
    ScenarioDefinition(
        scenario_id="hdfs_datanode_failure",
        title="HDFS DataNode failure",
        description=(
            "A DataNode reports I/O failures and missing block replicas, degrading the HDFS path."
        ),
        affected_entity_ids=("datanode-01", "namenode-01", "hdfs-client-01"),
        duration_seconds=90,
        expected_signals=("DataNode failure", "I/O error rate", "replica degradation"),
        difficulty="advanced",
        reference_datasets=("Loghub HDFS",),
        transformation_version="reference-scenario-builder-1.0",
        quality_flag="REFERENCE_DERIVED",
    ),
    ScenarioDefinition(
        scenario_id="trace_anomaly",
        title="Distributed trace anomaly",
        description=(
            "A payment span exceeds its expected p99 and a second span references a "
            "missing parent, exposing latency and structural trace anomalies."
        ),
        affected_entity_ids=("checkout-api-01", "payment-api-01"),
        duration_seconds=60,
        expected_signals=("critical-path latency", "span error", "missing parent span"),
        difficulty="advanced",
        reference_datasets=("Sample traces",),
        transformation_version="reference-scenario-builder-1.0",
        quality_flag="REFERENCE_DERIVED",
    ),
    ScenarioDefinition(
        scenario_id="database_connection_pool_exhaustion",
        title="Database connection-pool exhaustion",
        description=(
            "The payment database pool saturates, producing rejected leases, dependency "
            "timeouts, and checkout degradation."
        ),
        affected_entity_ids=("payment-db-01", "payment-api-01", "checkout-api-01"),
        duration_seconds=90,
        expected_signals=(
            "database utilization",
            "pool exhaustion",
            "dependency timeout",
        ),
        difficulty="intermediate",
    ),
    ScenarioDefinition(
        scenario_id="dns_resolution_failure",
        title="DNS resolution failure",
        description=(
            "Checkout service DNS lookups fail, preventing connections to dependent services."
        ),
        affected_entity_ids=("checkout-api-01", "payment-api-01"),
        duration_seconds=60,
        expected_signals=("DNS resolver errors", "connection failures"),
        difficulty="intermediate",
    ),
    ScenarioDefinition(
        scenario_id="tls_certificate_failure",
        title="TLS certificate failure",
        description=(
            "The payment service presents an invalid certificate and callers fail TLS handshakes."
        ),
        affected_entity_ids=("payment-api-01", "checkout-api-01"),
        duration_seconds=60,
        expected_signals=("certificate invalid", "TLS handshake failure"),
        difficulty="intermediate",
    ),
)

_BY_ID = {scenario.scenario_id: scenario for scenario in SCENARIOS}
_ALIASES = {
    "gateway_rate_limit": PRIMARY_SCENARIO_KEY,
    PRIMARY_SCENARIO_ID: PRIMARY_SCENARIO_KEY,
    PRIMARY_TRACE_ID: PRIMARY_SCENARIO_KEY,
}


def list_scenarios() -> tuple[ScenarioDefinition, ...]:
    return SCENARIOS


def resolve_scenario_id(value: str) -> str:
    scenario_id = _ALIASES.get(value, value)
    if scenario_id not in _BY_ID:
        raise KeyError(value)
    return scenario_id


def _syslog(
    *,
    scenario_id: str,
    offset_seconds: int,
    record_id: str,
    host: str,
    code: str,
    message: str,
    level: str = "error",
    dependency_id: str | None = None,
    attributes: dict | None = None,
) -> tuple[str, dict]:
    timestamp = TRIGGER_TIME + timedelta(seconds=offset_seconds)
    raw = SyslogEmitter().emit(
        record_id=record_id,
        timestamp=timestamp,
        host=host,
        facility="application",
        level=level,
        code=code,
        message=message,
        trace_id=scenario_id,
        attributes=attributes or {},
        scenario_id=scenario_id,
        provenance=_provenance(scenario_id),
    )
    if dependency_id is not None:
        raw["payload"]["dependency_id"] = dependency_id
    return SyslogEmitter.source_name, raw


def _metric(
    *,
    scenario_id: str,
    offset_seconds: int,
    sample_id: str,
    entity_id: str,
    metric: str,
    value: float,
    unit: str,
) -> tuple[str, dict]:
    timestamp = TRIGGER_TIME + timedelta(seconds=offset_seconds)
    raw = PrometheusEmitter().emit(
        sample_id=sample_id,
        observed_at=timestamp,
        metric=metric,
        value=value,
        unit=unit,
        labels={"entity_id": entity_id},
        scenario_id=scenario_id,
        provenance=_provenance(scenario_id),
    )
    return PrometheusEmitter.source_name, raw


def _provenance(scenario_id: str) -> dict | None:
    scenario = _BY_ID.get(scenario_id)
    if scenario is None or scenario.quality_flag != "REFERENCE_DERIVED":
        return None
    return {
        "origin": list(scenario.reference_datasets),
        "origin_record_id": f"curated-profile:{scenario_id}",
        "retrieved_at": "2026-07-16",
        "license_reference": "dataset-owner research terms",
        "transformation_version": scenario.transformation_version,
        "synthetic_fields": ["timestamp", "entity_id", "trace_id", "record_id"],
        "seed": 20260714,
        "quality_flags": ["REFERENCE_DERIVED"],
    }


def _alert(
    *,
    scenario_id: str,
    offset_seconds: int,
    fingerprint: str,
    entity_id: str,
    alertname: str,
    severity: str,
    summary: str,
) -> tuple[str, dict]:
    timestamp = TRIGGER_TIME + timedelta(seconds=offset_seconds)
    raw = AlertmanagerEmitter().emit(
        fingerprint=fingerprint,
        starts_at=timestamp,
        status="firing",
        labels={
            "entity_id": entity_id,
            "alertname": alertname,
            "severity": severity,
        },
        annotations={"summary": summary},
        scenario_id=scenario_id,
        provenance=_provenance(scenario_id),
    )
    return AlertmanagerEmitter.source_name, raw


def _trace(
    *,
    scenario_id: str,
    offset_seconds: int,
    span_id: str,
    entity_id: str,
    trace_id: str,
    parent_span_id: str | None,
    operation: str,
    duration_ms: float,
    expected_p99_ms: float,
    status: str = "ok",
    peer_service: str | None = None,
) -> tuple[str, dict]:
    timestamp = TRIGGER_TIME + timedelta(seconds=offset_seconds)
    raw = TraceEmitter().emit(
        span_id=span_id,
        observed_at=timestamp,
        entity_id=entity_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        operation=operation,
        duration_ms=duration_ms,
        expected_p99_ms=expected_p99_ms,
        status=status,
        peer_service=peer_service,
        scenario_id=scenario_id,
        provenance=_provenance(scenario_id),
    )
    return TraceEmitter.source_name, raw


def _generated_groups(scenario_id: str) -> list[ScheduledGroup]:
    records: tuple[tuple[str, dict], ...]
    if scenario_id == "database_connection_pool_exhaustion":
        records = (
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="db-pool-utilization-001",
                entity_id="payment-db-01",
                metric="db_connection_utilization",
                value=0.98,
                unit="ratio",
            ),
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="db-pool-exhausted-001",
                host="payment-db-01",
                code="DB_CONNECTION_POOL_EXHAUSTED",
                message="Payment database connection pool rejected new leases",
            ),
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="db-upstream-timeout-001",
                host="payment-api-01",
                code="UPSTREAM_CONNECTION_TIMEOUT",
                message="Payment API timed out waiting for the database pool",
                dependency_id="payment-db-01",
            ),
        )
        return [ScheduledGroup(TRIGGER_TIME, records)]
    if scenario_id == "network_path_congestion":
        records = (
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="network-packet-loss-rate-001",
                entity_id="api-gateway-01",
                metric="packet_loss_rate",
                value=0.18,
                unit="ratio",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="network-retransmissions-001",
                entity_id="api-gateway-01",
                metric="tcp_retransmissions_total",
                value=480.0,
                unit="count/10s",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="network-path-latency-001",
                entity_id="checkout-api-01",
                metric="network_latency_ms",
                value=320.0,
                unit="ms",
            ),
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="network-packet-loss-001",
                host="api-gateway-01",
                code="PACKET_LOSS_WARNING",
                message="Packet loss exceeded the service path threshold",
            ),
            _alert(
                scenario_id=scenario_id,
                offset_seconds=0,
                fingerprint="network-path-degraded-001",
                entity_id="api-gateway-01",
                alertname="NetworkPathDegraded",
                severity="critical",
                summary="Gateway-to-checkout path is degraded",
            ),
        )
        return [ScheduledGroup(TRIGGER_TIME, records)]
    if scenario_id == "ddos_syn_flood":
        records = (
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="ddos-ingress-001",
                entity_id="api-gateway-01",
                metric="raw_ingress_requests_per_second",
                value=18000.0,
                unit="requests/s",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="ddos-forwarded-001",
                entity_id="api-gateway-01",
                metric="forwarded_requests_per_second",
                value=15000.0,
                unit="requests/s",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="ddos-connections-001",
                entity_id="api-gateway-01",
                metric="active_connections_total",
                value=8000.0,
                unit="connections",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="ddos-syn-error-001",
                entity_id="api-gateway-01",
                metric="syn_error_rate",
                value=0.82,
                unit="ratio",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="ddos-source-shift-001",
                entity_id="api-gateway-01",
                metric="source_distribution_change_score",
                value=0.91,
                unit="score",
            ),
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="ddos-syn-flood-001",
                host="api-gateway-01",
                code="SYN_FLOOD_DETECTED",
                message="SYN backlog pressure and distributed source fan-in detected",
                level="critical",
            ),
            _alert(
                scenario_id=scenario_id,
                offset_seconds=0,
                fingerprint="ddos-syn-flood-alert-001",
                entity_id="api-gateway-01",
                alertname="SynFloodSuspected",
                severity="critical",
                summary="Traffic pattern is consistent with a SYN flood",
            ),
        )
        return [ScheduledGroup(TRIGGER_TIME, records)]
    if scenario_id == "gaia_resource_saturation":
        records = (
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="gaia-cpu-001",
                entity_id="payment-api-01",
                metric="cpu_usage_percent",
                value=98.0,
                unit="percent",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="gaia-memory-001",
                entity_id="payment-api-01",
                metric="memory_usage_percent",
                value=94.0,
                unit="percent",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="gaia-service-latency-001",
                entity_id="payment-api-01",
                metric="service_p95_latency_ms",
                value=1600.0,
                unit="ms",
            ),
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="gaia-resource-saturation-001",
                host="payment-api-01",
                code="RESOURCE_SATURATION",
                message="Payment service CPU and memory pressure exceeded safe limits",
                level="critical",
            ),
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="gaia-upstream-timeout-001",
                host="checkout-api-01",
                code="UPSTREAM_TIMEOUT",
                message="Checkout timed out waiting for the saturated payment service",
                dependency_id="payment-api-01",
            ),
        )
        return [ScheduledGroup(TRIGGER_TIME, records)]
    if scenario_id == "port_scan_reconnaissance":
        records = (
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="scan-port-fanout-001",
                entity_id="api-gateway-01",
                metric="unique_destination_ports",
                value=950.0,
                unit="ports/60s",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="scan-rejection-rate-001",
                entity_id="api-gateway-01",
                metric="rejected_connection_rate",
                value=0.87,
                unit="ratio",
            ),
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="scan-destination-fanout-001",
                entity_id="api-gateway-01",
                metric="destination_fanout",
                value=300.0,
                unit="destinations/60s",
            ),
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="scan-recon-001",
                host="api-gateway-01",
                code="PORT_SCAN_DETECTED",
                message="One source probed many destination ports and services",
                level="critical",
                attributes={"source_fingerprint": "reference-scanner-cluster-01"},
            ),
            _alert(
                scenario_id=scenario_id,
                offset_seconds=0,
                fingerprint="scan-recon-alert-001",
                entity_id="api-gateway-01",
                alertname="ReconnaissanceSuspected",
                severity="critical",
                summary="Port and destination fanout indicates reconnaissance",
            ),
        )
        return [ScheduledGroup(TRIGGER_TIME, records)]
    if scenario_id == "hdfs_datanode_failure":
        records = (
            _metric(
                scenario_id=scenario_id,
                offset_seconds=0,
                sample_id="hdfs-io-error-rate-001",
                entity_id="datanode-01",
                metric="datanode_io_error_rate",
                value=0.92,
                unit="ratio",
            ),
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="hdfs-datanode-failure-001",
                host="datanode-01",
                code="HDFS_DATANODE_FAILURE",
                message="DataNode volume failed and block replicas became unavailable",
                level="critical",
                dependency_id="namenode-01",
            ),
            _alert(
                scenario_id=scenario_id,
                offset_seconds=0,
                fingerprint="hdfs-replica-alert-001",
                entity_id="namenode-01",
                alertname="HdfsReplicaUnderReplicated",
                severity="critical",
                summary="HDFS blocks are under-replicated after a DataNode failure",
            ),
        )
        return [ScheduledGroup(TRIGGER_TIME, records)]
    if scenario_id == "trace_anomaly":
        trace_id = "trace-reference-anomaly-001"
        return [
            ScheduledGroup(
                TRIGGER_TIME,
                (
                    _trace(
                        scenario_id=scenario_id,
                        offset_seconds=0,
                        span_id="span-checkout-root-001",
                        entity_id="checkout-api-01",
                        trace_id=trace_id,
                        parent_span_id=None,
                        operation="POST /checkout",
                        duration_ms=180.0,
                        expected_p99_ms=250.0,
                        peer_service="payment-api-01",
                    ),
                ),
            ),
            ScheduledGroup(
                TRIGGER_TIME + timedelta(seconds=1),
                (
                    _trace(
                        scenario_id=scenario_id,
                        offset_seconds=1,
                        span_id="span-payment-latency-001",
                        entity_id="payment-api-01",
                        trace_id=trace_id,
                        parent_span_id="span-checkout-root-001",
                        operation="POST /payments/authorize",
                        duration_ms=1450.0,
                        expected_p99_ms=120.0,
                        status="error",
                        peer_service="payment-db-01",
                    ),
                ),
            ),
            ScheduledGroup(
                TRIGGER_TIME + timedelta(seconds=2),
                (
                    _trace(
                        scenario_id=scenario_id,
                        offset_seconds=2,
                        span_id="span-orphan-001",
                        entity_id="payment-api-01",
                        trace_id=trace_id,
                        parent_span_id="span-missing-999",
                        operation="payment.retry",
                        duration_ms=80.0,
                        expected_p99_ms=120.0,
                        peer_service="payment-db-01",
                    ),
                ),
            ),
        ]
    if scenario_id == "dns_resolution_failure":
        records = (
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="dns-resolution-failed-001",
                host="checkout-api-01",
                code="DNS_RESOLUTION_FAILED",
                message="Checkout could not resolve payment-api.internal",
            ),
        )
        return [ScheduledGroup(TRIGGER_TIME, records)]
    if scenario_id == "tls_certificate_failure":
        records = (
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="tls-handshake-failed-001",
                host="payment-api-01",
                code="TLS_HANDSHAKE_ERROR",
                message="TLS handshake rejected an invalid payment service certificate",
            ),
        )
        return [ScheduledGroup(TRIGGER_TIME, records)]
    raise KeyError(scenario_id)


def groups_for_scenario(value: str) -> tuple[str, list[ScheduledGroup]]:
    scenario_id = resolve_scenario_id(value)
    groups = (
        primary_scenario_groups()
        if scenario_id == PRIMARY_SCENARIO_KEY
        else _generated_groups(scenario_id)
    )
    return scenario_id, groups
