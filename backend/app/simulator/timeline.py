import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.simulator.emitters import AlertmanagerEmitter, ConfigAuditEmitter, PrometheusEmitter, SyslogEmitter

TRIGGER_TIME = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)
SCENARIO_ID = "gateway_rate_limit_disabled"
TRACE_ID = "scenario_gateway_rate_limit_001"


@dataclass(frozen=True)
class ScheduledGroup:
    timestamp: datetime
    records: tuple[tuple[str, dict], ...]


_INPUTS = Path(__file__).parents[1] / "fixtures/scenarios/gateway_rate_limit/inputs"
_EMITTERS = {
    "metrics.jsonl": PrometheusEmitter(),
    "logs.jsonl": SyslogEmitter(),
    "alerts.jsonl": AlertmanagerEmitter(),
    "config_changes.jsonl": ConfigAuditEmitter(),
}


def all_groups() -> list[ScheduledGroup]:
    grouped: dict[datetime, list[tuple[str, dict]]] = {}
    for filename, emitter in _EMITTERS.items():
        with (_INPUTS / filename).open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                raw = emitter.replay(json.loads(line))
                timestamp = datetime.fromisoformat(raw["emitted_at"].replace("Z", "+00:00"))
                grouped.setdefault(timestamp, []).append((emitter.source_name, raw))
    return [ScheduledGroup(timestamp, tuple(grouped[timestamp])) for timestamp in sorted(grouped)]


def baseline_groups() -> list[ScheduledGroup]:
    return [group for group in all_groups() if group.timestamp < TRIGGER_TIME]


def scenario_groups() -> list[ScheduledGroup]:
    return [group for group in all_groups() if group.timestamp >= TRIGGER_TIME]
