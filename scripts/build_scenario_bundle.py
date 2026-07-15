from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.contracts import AnomalyRecord, CanonicalEvent  # noqa: E402
from app.detection import (  # noqa: E402
    AlertSeverityDetector,
    ConfigChangeMarker,
    DetectionContext,
    LogRuleDetector,
    RollingZscoreDetector,
)
from app.ingestion.adapters import ADAPTERS  # noqa: E402


FIXTURES = ROOT / "backend" / "app" / "fixtures"
SCENARIO = FIXTURES / "scenarios" / "gateway_rate_limit"
INPUTS = SCENARIO / "inputs"
TEST_FIXTURES = ROOT / "backend" / "tests" / "fixtures"
ADAPTER_FIXTURES = TEST_FIXTURES / "source_adapters"
PROFILE_PATH = FIXTURES / "reference_profiles" / "network_profile.json"
T = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)
SEED = 20260714
SCENARIO_KEY = "gateway_rate_limit_disabled"
SCENARIO_ID = "scenario_gateway_rate_limit_001"
TRACE_ID = SCENARIO_ID
GENERATED_AT = "2026-07-14T09:00:00.000Z"


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pretty(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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
            if name == "forwarded_requests_per_second" and point >= 3:
                # The detector window at T+30 contains points 3..29. Four
                # symmetric pairs followed by 19 mean values preserve the
                # frozen rolling z=4.25 while allowing the later EWMA baseline
                # to settle before the scenario spike.
                if point <= 10:
                    target_std = (7800.0 - baseline) / 4.25
                    deviation = target_std * ((26 / 8) ** 0.5)
                    value = baseline + (deviation if point % 2 else -deviation)
                else:
                    value = baseline
            else:
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


def _anomaly_json(anomaly: AnomalyRecord) -> dict[str, Any]:
    value = anomaly.model_dump(mode="json")
    for field in ("detected_at", "window_start", "window_end"):
        value[field] = iso(getattr(anomaly, field))
    return value


def build_anomalies(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate the handoff manifest from the production Person 3 detectors."""

    detectors = (
        RollingZscoreDetector(),
        LogRuleDetector(),
        AlertSeverityDetector(),
        ConfigChangeMarker(),
    )
    history: list[CanonicalEvent] = []
    anomalies: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    canonical = sorted(
        (CanonicalEvent.model_validate(event) for event in events),
        key=lambda event: (event.timestamp, event.event_id),
    )
    for event in canonical:
        context = DetectionContext(history=list(history))
        for detector in detectors:
            for anomaly in detector.evaluate(event, context):
                target = markers if anomaly.context_only else anomalies
                target.append(_anomaly_json(anomaly))
        history.append(event)

    anomalies.sort(key=lambda item: (item["window_end"], item["event_id"], item["detector_id"]))
    markers.sort(key=lambda item: (item["window_end"], item["event_id"], item["detector_id"]))
    if len(anomalies) != 9 or len(markers) != 1:
        raise ValueError(
            f"golden detector output must remain 9 actionable + 1 context marker; got {len(anomalies)} + {len(markers)}"
        )
    return {
        "schema_version": "1.0",
        "version": "golden-anomalies-1.0",
        "scenario_id": SCENARIO_ID,
        "actionable_anomaly_count": 9,
        "anomalies": anomalies,
        "context_markers": markers,
    }


def jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(compact(record) + "\n" for record in records)


def build_outputs() -> dict[Path, str]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    streams = build_raw_streams(profile)
    outputs: dict[Path, str] = {
        INPUTS / f"{name}.jsonl": jsonl(records) for name, records in streams.items()
    }
    source_names = {
        "metrics": "simulator.prometheus",
        "logs": "simulator.syslog",
        "alerts": "simulator.alertmanager",
        "config_changes": "simulator.config_audit",
    }
    canonical_events = [
        ADAPTERS[source_names[name]].adapt(record)
        for name in ("metrics", "logs", "alerts", "config_changes")
        for record in streams[name]
    ]
    events = []
    for event in canonical_events:
        value = event.model_dump(mode="json")
        value["timestamp"] = iso(event.timestamp)
        value["ingested_at"] = iso(event.ingested_at)
        events.append(value)
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


def run(*, check: bool) -> None:
    outputs = build_outputs()
    mismatches = []
    for path, content in outputs.items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                mismatches.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if mismatches:
        raise SystemExit("scenario bundle is stale: " + ", ".join(mismatches))
    print(f"{'validated' if check else 'generated'} {len(outputs)} deterministic artifacts")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if checked-in outputs differ")
    args = parser.parse_args()
    run(check=args.check)


if __name__ == "__main__":
    main()
