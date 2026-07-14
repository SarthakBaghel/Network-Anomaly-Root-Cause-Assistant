from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "backend" / "app" / "fixtures"
SCENARIO = FIXTURES / "scenarios" / "gateway_rate_limit"
INPUTS = SCENARIO / "inputs"
TEST_FIXTURES = ROOT / "backend" / "tests" / "fixtures"
ADAPTER_FIXTURES = TEST_FIXTURES / "source_adapters"
PROFILE_PATH = FIXTURES / "reference_profiles" / "network_profile.json"
T = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)
SEED = 20260714
SCENARIO_ID = "gateway_rate_limit_disabled"
TRACE_ID = "scenario_gateway_rate_limit_001"
GENERATED_AT = "2026-07-14T09:00:00.000Z"


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pretty(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def stable_id(prefix: str, source_record_id: str) -> str:
    return f"{prefix}_{hashlib.sha256(source_record_id.encode()).hexdigest()[:24]}"


def envelope(emitted_at: datetime, payload: dict[str, Any], origin: str) -> dict[str, Any]:
    return {
        "scenario_id": SCENARIO_ID,
        "emitted_at": iso(emitted_at),
        "provenance": {
            "origin": origin,
            "transformation_version": "scenario-builder-1.0",
            "synthetic_fields": ["entity_id", "trace_or_session_id", "scenario_relative_time"],
            "seed": SEED,
        },
        "payload": payload,
    }


def metric_record(
    timestamp: datetime,
    sequence: int,
    entity_id: str,
    metric: str,
    value: float,
    unit: str,
) -> dict[str, Any]:
    return envelope(
        timestamp,
        {
            "sample_id": f"prom-{metric}-{sequence:04d}",
            "observed_at": iso(timestamp),
            "metric": metric,
            "value": value,
            "unit": unit,
            "labels": {"entity_id": entity_id, "service": entity_id.rsplit("-01", 1)[0]},
        },
        "deterministic-simulator/prometheus",
    )


def build_raw_streams(profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    signals = profile["signals"]
    metric_specs = {
        "raw_ingress_requests_per_second": ("api-gateway-01", 7800.0),
        "forwarded_requests_per_second": ("api-gateway-01", 2400.0),
        "active_connections_total": ("api-gateway-01", 1200.0),
        "connection_utilization": ("api-gateway-01", 0.35),
        "tcp_resets_total": ("api-gateway-01", 2.0),
        "tcp_retransmissions_total": ("api-gateway-01", 6.0),
        "checkout_p95_latency_ms": ("checkout-api-01", 180.0),
        "db_connection_utilization": ("payment-db-01", 0.42),
    }
    metrics: list[dict[str, Any]] = []
    sequence = 0
    for point in range(30):
        timestamp = T - timedelta(seconds=300 - point * 10)
        for name, (entity, baseline) in metric_specs.items():
            sequence += 1
            jitter = ((point % 5) - 2) * 0.002
            value = baseline * (1 + jitter)
            metrics.append(
                metric_record(timestamp, sequence, entity, name, round(value, 4), signals[name]["unit"])
            )

    changed = [
        (30, "api-gateway-01", "raw_ingress_requests_per_second", 7800.0),
        (30, "api-gateway-01", "forwarded_requests_per_second", 7800.0),
        (30, "api-gateway-01", "active_connections_total", 4100.0),
        (30, "api-gateway-01", "connection_utilization", 0.92),
        (40, "api-gateway-01", "tcp_resets_total", 48.0),
        (40, "api-gateway-01", "tcp_retransmissions_total", 72.0),
        (60, "checkout-api-01", "checkout_p95_latency_ms", 1250.0),
        (100, "payment-db-01", "db_connection_utilization", 0.44),
    ]
    for offset, entity, name, value in changed:
        sequence += 1
        metrics.append(metric_record(T + timedelta(seconds=offset), sequence, entity, name, value, signals[name]["unit"]))

    logs = [
        envelope(
            T - timedelta(seconds=10),
            {
                "record_id": "log-gateway-health-0001",
                "observed_at": iso(T - timedelta(seconds=10)),
                "host": "api-gateway-01",
                "facility": "application",
                "level": "info",
                "code": "HEALTH_CHECK_OK",
                "message": "Gateway health check succeeded",
                "trace_id": TRACE_ID,
            },
            "deterministic-simulator/syslog",
        ),
        envelope(
            T + timedelta(seconds=75),
            {
                "record_id": "log-payment-timeout-0001",
                "observed_at": iso(T + timedelta(seconds=75)),
                "host": "payment-api-01",
                "facility": "application",
                "level": "error",
                "code": "UPSTREAM_CONNECTION_TIMEOUT",
                "message": "Upstream dependency payment-db-01 timed out after 2000 ms",
                "trace_id": TRACE_ID,
                "dependency_id": "payment-db-01",
            },
            "deterministic-simulator/syslog",
        ),
        envelope(
            T + timedelta(seconds=120),
            {
                "record_id": "log-auth-certificate-0001",
                "observed_at": iso(T + timedelta(seconds=120)),
                "host": "auth-api-01",
                "facility": "security",
                "level": "warning",
                "code": "CERTIFICATE_EXPIRY_WARNING",
                "message": "Certificate expires in 20 days",
                "trace_id": "maintenance_auth_001",
            },
            "deterministic-simulator/syslog",
        ),
    ]

    alerts = [
        envelope(
            T + timedelta(seconds=45),
            {
                "fingerprint": "alert-gateway-forwarded-0001",
                "startsAt": iso(T + timedelta(seconds=45)),
                "status": "firing",
                "labels": {
                    "entity_id": "api-gateway-01",
                    "alertname": "HighForwardedRequestAndConnectionRate",
                    "severity": "critical",
                },
                "annotations": {"summary": "Forwarded requests and active connections exceed limits"},
            },
            "deterministic-simulator/alertmanager",
        ),
        envelope(
            T + timedelta(seconds=90),
            {
                "fingerprint": "alert-checkout-error-0001",
                "startsAt": iso(T + timedelta(seconds=90)),
                "status": "firing",
                "labels": {
                    "entity_id": "checkout-api-01",
                    "alertname": "HighCheckoutErrorRate",
                    "severity": "critical",
                },
                "annotations": {"summary": "Checkout error rate exceeds threshold"},
            },
            "deterministic-simulator/alertmanager",
        ),
    ]

    config_changes = [
        envelope(
            T,
            {
                "change_id": "config-change-000001",
                "changed_at": iso(T),
                "target_entity_id": "api-gateway-01",
                "actor": "deploy-bot",
                "config_key": "rate_limit.enabled",
                "old_value": True,
                "new_value": False,
                "change_ticket": "CHG-DEMO-001",
            },
            "deterministic-simulator/config-audit",
        )
    ]
    return {"metrics": metrics, "logs": logs, "alerts": alerts, "config_changes": config_changes}


METRIC_EVENT_TYPES = {
    "raw_ingress_requests_per_second": "RAW_INGRESS_RATE",
    "forwarded_requests_per_second": "FORWARDED_REQUEST_RATE",
    "active_connections_total": "ACTIVE_CONNECTIONS",
    "connection_utilization": "CONNECTION_UTILIZATION",
    "tcp_resets_total": "TCP_RESETS",
    "tcp_retransmissions_total": "TCP_RETRANSMISSIONS",
    "checkout_p95_latency_ms": "CHECKOUT_P95_LATENCY",
    "db_connection_utilization": "DB_CONNECTION_UTILIZATION",
}

ALERT_EVENT_TYPES = {
    "HighForwardedRequestAndConnectionRate": "HIGH_FORWARDED_REQUEST_AND_CONNECTION_RATE",
    "HighCheckoutErrorRate": "HIGH_CHECKOUT_ERROR_RATE",
}


def canonical_event(source_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    payload = raw["payload"]
    provenance = raw["provenance"]
    if source_type == "metrics":
        source = "simulator.prometheus"
        source_id = payload["sample_id"]
        timestamp = payload["observed_at"]
        entity = payload["labels"]["entity_id"]
        event_type = METRIC_EVENT_TYPES[payload["metric"]]
        severity = 0.0
        signal = (payload["metric"], payload["value"], payload["unit"])
        trace = TRACE_ID
    elif source_type == "logs":
        source = "simulator.syslog"
        source_id = payload["record_id"]
        timestamp = payload["observed_at"]
        entity = payload["host"]
        event_type = payload["code"]
        severity = {"info": 0.2, "warning": 0.35, "error": 0.88}[payload["level"]]
        signal = (None, None, None)
        trace = payload.get("trace_id") or TRACE_ID
    elif source_type == "alerts":
        source = "simulator.alertmanager"
        source_id = payload["fingerprint"]
        timestamp = payload["startsAt"]
        entity = payload["labels"]["entity_id"]
        event_type = ALERT_EVENT_TYPES[payload["labels"]["alertname"]]
        severity = {"info": 0.25, "warning": 0.6, "critical": 0.95}[payload["labels"]["severity"]]
        signal = (None, None, None)
        trace = TRACE_ID
    else:
        source = "simulator.config_audit"
        source_id = payload["change_id"]
        timestamp = payload["changed_at"]
        entity = payload["target_entity_id"]
        event_type = "CONFIG_VALUE_CHANGED"
        severity = 0.0
        signal = (None, None, None)
        trace = TRACE_ID

    timestamp_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    raw_payload = dict(payload)
    if source_type == "config_changes":
        raw_payload["context_only"] = True
    raw_payload["scenario_id"] = raw["scenario_id"]
    raw_payload["provenance"] = provenance
    return {
        "event_id": stable_id("evt", source_id),
        "timestamp": timestamp,
        "ingested_at": iso(timestamp_dt + timedelta(milliseconds=120)),
        "entity_id": entity,
        "modality": {
            "metrics": "metric",
            "logs": "log",
            "alerts": "alert",
            "config_changes": "config_change",
        }[source_type],
        "event_type": event_type,
        "severity": severity,
        "signal_name": signal[0],
        "signal_value": signal[1],
        "unit": signal[2],
        "trace_or_session_id": trace,
        "source": source,
        "source_record_id": source_id,
        "schema_version": "1.0",
        "quality_flags": ["SIMULATED"],
        "raw_payload": raw_payload,
    }


def build_anomalies(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_source = {event["source_record_id"]: event for event in events}
    definitions = [
        ("prom-forwarded_requests_per_second-0242", "rolling_zscore_v1", "FORWARDED_TRAFFIC_SPIKE", 0.91),
        ("prom-active_connections_total-0243", "rolling_zscore_v1", "ACTIVE_CONNECTION_SPIKE", 0.89),
        ("prom-connection_utilization-0244", "rolling_zscore_v1", "CONNECTION_UTILIZATION_HIGH", 0.94),
        ("prom-tcp_resets_total-0245", "rolling_zscore_v1", "TCP_RESET_SPIKE", 0.85),
        ("prom-tcp_retransmissions_total-0246", "rolling_zscore_v1", "TCP_RETRANSMISSION_SPIKE", 0.87),
        ("alert-gateway-forwarded-0001", "alert_severity_v1", "GATEWAY_TRAFFIC_ALERT", 0.95),
        ("prom-checkout_p95_latency_ms-0247", "rolling_zscore_v1", "CHECKOUT_LATENCY_HIGH", 0.88),
        ("log-payment-timeout-0001", "log_rule_v1", "UPSTREAM_TIMEOUT", 0.86),
        ("alert-checkout-error-0001", "alert_severity_v1", "CHECKOUT_ERROR_ALERT", 0.95),
    ]
    anomalies = []
    for source_id, detector_id, anomaly_type, score in definitions:
        event = by_source[source_id]
        at = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        anomalies.append(
            {
                "anomaly_id": stable_id("ano", source_id),
                "event_id": event["event_id"],
                "detector_id": detector_id,
                "detected_at": iso(at + timedelta(milliseconds=200)),
                "anomaly_type": anomaly_type,
                "score": score,
                "threshold": 0.75,
                "context_only": False,
                "can_open_incident": True,
                "window_start": iso(at - timedelta(seconds=300)),
                "window_end": event["timestamp"],
                "features": {"source_record_id": source_id},
                "explanation": f"{anomaly_type} matched the frozen detector rule.",
            }
        )
    config = by_source["config-change-000001"]
    marker = {
        "anomaly_id": stable_id("ctx", "config-change-000001"),
        "event_id": config["event_id"],
        "detector_id": "config_change_marker_v1",
        "detected_at": "2026-07-14T09:30:00.200Z",
        "anomaly_type": "RECENT_CONFIGURATION_CHANGE",
        "score": 0.0,
        "threshold": 0.75,
        "context_only": True,
        "can_open_incident": False,
        "window_start": "2026-07-14T09:25:00.000Z",
        "window_end": "2026-07-14T09:30:00.000Z",
        "features": {"change_ticket": "CHG-DEMO-001"},
        "explanation": "Configuration changes are retained as context and cannot open an incident.",
    }
    return {
        "schema_version": "1.0",
        "version": "golden-anomalies-1.0",
        "scenario_id": SCENARIO_ID,
        "actionable_anomaly_count": 9,
        "anomalies": anomalies,
        "context_markers": [marker],
    }


def jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(compact(record) + "\n" for record in records)


def build_outputs() -> dict[Path, str]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    streams = build_raw_streams(profile)
    outputs: dict[Path, str] = {
        INPUTS / f"{name}.jsonl": jsonl(records) for name, records in streams.items()
    }
    events = [
        canonical_event(name, record)
        for name in ("metrics", "logs", "alerts", "config_changes")
        for record in streams[name]
    ]
    events.sort(key=lambda event: (event["timestamp"], event["event_id"]))
    outputs[TEST_FIXTURES / "golden_events.jsonl"] = jsonl(events)
    anomalies = build_anomalies(events)
    outputs[TEST_FIXTURES / "golden_anomalies.json"] = pretty(anomalies)

    by_source = {event["source_record_id"]: event for event in events}
    scenario_sources = [
        "config-change-000001",
        "prom-raw_ingress_requests_per_second-0241",
        "prom-forwarded_requests_per_second-0242",
        "prom-active_connections_total-0243",
        "prom-connection_utilization-0244",
        "prom-tcp_resets_total-0245",
        "prom-tcp_retransmissions_total-0246",
        "alert-gateway-forwarded-0001",
        "prom-checkout_p95_latency_ms-0247",
        "log-payment-timeout-0001",
        "alert-checkout-error-0001",
        "prom-db_connection_utilization-0248",
    ]
    ground_truth = {
        "schema_version": "1.0",
        "version": "ground-truth-1.0",
        "scenario_id": SCENARIO_ID,
        "probable_cause": {"hypothesis_type": "configuration_regression", "entity_id": "api-gateway-01"},
        "attached_event_ids": [by_source[source]["event_id"] for source in scenario_sources],
        "excluded_event_ids": [by_source["log-auth-certificate-0001"]["event_id"]],
        "expected_scores": [92.1, 65.6, 41.5],
    }
    outputs[SCENARIO / "expected" / "ground_truth.json"] = pretty(ground_truth)

    adapter_examples = {
        "valid_prometheus_sample.json": streams["metrics"][-7]["payload"],
        "invalid_prometheus_sample.json": {
            **streams["metrics"][-7]["payload"],
            "labels": {"service": "api-gateway"},
        },
        "valid_syslog_record.json": streams["logs"][1]["payload"],
        "invalid_syslog_record.json": {
            key: value for key, value in streams["logs"][1]["payload"].items() if key != "host"
        },
        "valid_alertmanager_alert.json": streams["alerts"][0]["payload"],
        "invalid_alertmanager_alert.json": {
            key: value for key, value in streams["alerts"][0]["payload"].items() if key != "startsAt"
        },
        "valid_config_audit.json": streams["config_changes"][0]["payload"],
        "invalid_config_audit.json": {
            key: value
            for key, value in streams["config_changes"][0]["payload"].items()
            if key != "target_entity_id"
        },
    }
    for name, value in adapter_examples.items():
        outputs[ADAPTER_FIXTURES / name] = pretty(value)

    tracked = [PROFILE_PATH, FIXTURES / "reference_profiles" / "log_templates.yaml", *outputs.keys()]
    provenance_entries = []
    for path in tracked:
        if path == SCENARIO / "provenance.json" or "ground_truth" in path.name:
            continue
        content = outputs[path] if path in outputs else path.read_text(encoding="utf-8")
        provenance_entries.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": digest(content),
                "record_count": content.count("\n") if path.suffix == ".jsonl" else None,
                "origin": "checked-in-profile" if path.is_relative_to(FIXTURES / "reference_profiles") else "deterministic-simulator",
                "license": "project-authored synthetic fixture",
            }
        )
    outputs[SCENARIO / "provenance.json"] = pretty(
        {
            "schema_version": "1.0",
            "version": "scenario-provenance-1.0",
            "scenario_id": SCENARIO_ID,
            "seed": SEED,
            "builder_version": "scenario-builder-1.0",
            "generated_at": GENERATED_AT,
            "entries": sorted(provenance_entries, key=lambda entry: entry["path"]),
        }
    )
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if checked-in outputs differ")
    args = parser.parse_args()
    outputs = build_outputs()
    mismatches = []
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                mismatches.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if mismatches:
        raise SystemExit("scenario bundle is stale: " + ", ".join(mismatches))
    print(f"{'validated' if args.check else 'generated'} {len(outputs)} deterministic artifacts")


if __name__ == "__main__":
    main()
