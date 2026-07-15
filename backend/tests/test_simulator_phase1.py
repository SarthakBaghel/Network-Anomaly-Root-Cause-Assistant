import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.simulator as simulator_api
from app.main import app
from app.contracts import CanonicalEvent
from app.simulator.emitters import AlertmanagerEmitter, ConfigAuditEmitter, PrometheusEmitter, SyslogEmitter
from app.simulator.engine import SimulatorEngine
from app.simulator.ingestion import AdapterValidationSink


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_four_emitters_have_distinct_sources_shapes_and_common_envelope():
    at = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)
    scenario = "scenario_gateway_rate_limit_001"
    emitted = [
        (PrometheusEmitter(), PrometheusEmitter().emit(sample_id="sample", observed_at=at, metric="rps", value=1.0, unit="requests/s", labels={"entity_id": "api-gateway-01"}, scenario_id=scenario), {"sample_id", "observed_at", "metric", "value", "unit", "labels"}),
        (SyslogEmitter(), SyslogEmitter().emit(record_id="log", timestamp=at, host="payment-api-01", facility="application", level="ERROR", code="UPSTREAM_TIMEOUT", message="timeout", trace_id=scenario, attributes={}, scenario_id=scenario), {"record_id", "observed_at", "host", "facility", "level", "code", "message", "trace_id", "attributes"}),
        (AlertmanagerEmitter(), AlertmanagerEmitter().emit(fingerprint="alert", starts_at=at, status="firing", labels={"entity_id": "api-gateway-01", "alertname": "HighRate"}, annotations={}, scenario_id=scenario), {"fingerprint", "startsAt", "status", "labels", "annotations"}),
        (ConfigAuditEmitter(), ConfigAuditEmitter().emit(change_id="change", changed_at=at, target_entity_id="api-gateway-01", actor="bot", config_key="enabled", old_value=True, new_value=False, change_ticket="CHG-1", scenario_id=scenario), {"change_id", "changed_at", "target_entity_id", "actor", "config_key", "old_value", "new_value", "change_ticket"}),
    ]
    assert len({emitter.source_name for emitter, _, _ in emitted}) == 4
    for _, raw, payload_fields in emitted:
        assert set(raw) == {"scenario_id", "emitted_at", "provenance", "payload"}
        assert raw["scenario_id"] == scenario
        assert raw["provenance"]["seed"] == 20260714
        assert set(raw["payload"]) == payload_fields


def test_engine_lifecycle_virtual_ticks_and_reset_hook():
    sink = AdapterValidationSink()
    engine = SimulatorEngine(sink, background=False)
    assert engine.status()["virtual_clock"] == "2026-07-14T09:25:00Z"
    engine.start()
    engine.tick()
    assert engine.status()["virtual_clock"] == "2026-07-14T09:25:10Z"
    assert len(sink.accepted_events) == 8
    engine.pause()
    engine.tick()
    assert len(sink.accepted_events) == 8
    engine.resume()
    engine.tick()
    assert len(sink.accepted_events) == 16
    engine.stop()
    engine.reset()
    status = engine.status()
    assert status["state"] == "stopped" and status["baseline_ticks_emitted"] == 0
    assert len(sink.accepted_events) == 16  # P1 owns cross-domain clearing.


def test_trigger_emits_complete_golden_stream_only_through_ingestion():
    sink = AdapterValidationSink()
    engine = SimulatorEngine(sink, background=False)
    engine.start()
    status = engine.trigger("gateway_rate_limit")
    assert status["state"] == "completed"
    assert status["scenario_state"] == "completed"
    assert status["virtual_clock"] == "2026-07-14T09:32:00Z"
    assert len(sink.accepted_events) == 254
    assert status["sources"] == {
        "simulator.prometheus": {"emitted": 248, "accepted": 248, "collapsed": 0, "quarantined": 0},
        "simulator.config_audit": {"emitted": 1, "accepted": 1, "collapsed": 0, "quarantined": 0},
        "simulator.alertmanager": {"emitted": 2, "accepted": 2, "collapsed": 0, "quarantined": 0},
        "simulator.syslog": {"emitted": 3, "accepted": 3, "collapsed": 0, "quarantined": 0},
    }
    events = sorted(sink.accepted_events, key=lambda event: (event.ingested_at, event.event_id))
    expected = sorted(
        [
            CanonicalEvent.model_validate(json.loads(line))
            for line in (FIXTURES / "golden_events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ],
        key=lambda event: (event.ingested_at, event.event_id),
    )
    assert [event.model_dump() for event in events] == [event.model_dump() for event in expected]
    assert "app.db" not in inspect.getsource(type(engine))
    assert "analysis" not in inspect.getsource(type(engine)).lower()


def test_required_simulator_api_handlers(monkeypatch):
    isolated = SimulatorEngine(background=False)
    monkeypatch.setattr(simulator_api, "simulator_engine", isolated)
    with TestClient(app) as client:
        stopped_trigger = client.post("/api/v1/simulator/scenarios/gateway_rate_limit/trigger")
        assert stopped_trigger.status_code == 409
        start = client.post("/api/v1/simulator/start")
        assert start.status_code == 200
        assert start.json()["request_id"].startswith("req_")
        assert client.get("/api/v1/simulator/status").json()["state"] == "running"
        result = client.post("/api/v1/simulator/scenarios/gateway_rate_limit/trigger")
        assert result.status_code == 200 and result.json()["scenario_state"] == "completed"
        assert result.json()["request_id"].startswith("req_")
        assert client.post("/api/v1/simulator/scenarios/gateway_rate_limit/trigger").status_code == 409
        assert client.post("/api/v1/simulator/start").status_code == 409
        reset = client.post("/api/v1/simulator/reset").json()
        assert reset["scenario_state"] == "idle"
        assert reset["request_id"].startswith("req_")
        assert client.post("/api/v1/simulator/start").status_code == 200
        assert client.post("/api/v1/simulator/stop").json()["state"] == "stopped"
        assert client.post("/api/v1/simulator/scenarios/unknown/trigger").status_code == 404
