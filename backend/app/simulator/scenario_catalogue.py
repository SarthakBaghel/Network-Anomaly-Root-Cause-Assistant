from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from app.simulator.emitters import PrometheusEmitter, SyslogEmitter
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
        scenario_id="network_path_congestion",
        title="Network path congestion",
        description=(
            "Packet loss and TCP retransmissions appear between the gateway and checkout "
            "service, increasing downstream latency."
        ),
        affected_entity_ids=("api-gateway-01", "checkout-api-01"),
        duration_seconds=75,
        expected_signals=("packet loss", "TCP retransmissions", "path latency"),
        difficulty="advanced",
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
        attributes={},
        scenario_id=scenario_id,
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
    )
    return PrometheusEmitter.source_name, raw


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
        packet_loss = (
            _syslog(
                scenario_id=scenario_id,
                offset_seconds=0,
                record_id="network-packet-loss-001",
                host="api-gateway-01",
                code="PACKET_LOSS_WARNING",
                message="Packet loss exceeded the service path threshold",
            ),
        )
        retransmissions = (
            _metric(
                scenario_id=scenario_id,
                offset_seconds=5,
                sample_id="network-retransmissions-001",
                entity_id="api-gateway-01",
                metric="tcp_retransmissions_total",
                value=480.0,
                unit="packets",
            ),
        )
        return [
            ScheduledGroup(TRIGGER_TIME, packet_loss),
            ScheduledGroup(TRIGGER_TIME + timedelta(seconds=5), retransmissions),
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
