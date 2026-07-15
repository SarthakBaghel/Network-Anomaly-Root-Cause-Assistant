import threading
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.simulator.ingestion import IngestionSink, PersistentIngestionSink
from app.simulator.timeline import SCENARIO_ID, SCENARIO_KEY, TRACE_ID, TRIGGER_TIME, baseline_groups, scenario_groups

SIMULATOR_REAL_TICK_SECONDS = 0.05
SOURCE_TYPES = {
    "simulator.prometheus": "metrics",
    "simulator.syslog": "logs",
    "simulator.alertmanager": "alerts",
    "simulator.config_audit": "config_changes",
}
TOPOLOGY_SOURCE = "fixture.cmdb_topology"
TOPOLOGY_FIXTURE = Path(__file__).parents[1] / "fixtures/topology.json"


class SimulatorStateError(RuntimeError):
    pass


class SimulatorEngine:
    def __init__(self, ingestion: IngestionSink | None = None, *, background: bool = True) -> None:
        self.ingestion = ingestion or PersistentIngestionSink()
        self.background = background
        self._baseline = baseline_groups()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._cursor = 0
        self.state = "stopped"
        self.scenario_state = "idle"
        self.active_scenario: str | None = None
        self.virtual_clock = TRIGGER_TIME - timedelta(minutes=5)
        self.counters = defaultdict(lambda: {"emitted": 0, "accepted": 0, "collapsed": 0, "quarantined": 0})
        self.last_ingest_at: dict[str, str] = {}

    def start(self) -> dict:
        with self._lock:
            if self.state == "running":
                return self.status()
            if self._cursor >= len(self._baseline):
                self._cursor = 0
                self.virtual_clock = TRIGGER_TIME - timedelta(minutes=5)
            self.state = "running"
            self.scenario_state = "baseline"
            self._stop_event.clear()
            self._start_worker()
            return self.status()

    def stop(self) -> dict:
        self._stop_worker()
        with self._lock:
            self.state = "stopped"
            return self.status()

    def pause(self) -> dict:
        with self._lock:
            if self.state != "running":
                raise SimulatorStateError("only a running simulator can be paused")
            self.state = "paused"
            return self.status()

    def resume(self) -> dict:
        with self._lock:
            if self.state != "paused":
                raise SimulatorStateError("only a paused simulator can be resumed")
            self.state = "running"
            self._stop_event.clear()
            self._start_worker()
            return self.status()

    def reset(self) -> dict:
        """Reset only simulator-owned state; cross-domain data clearing belongs to P1."""
        self._stop_worker()
        with self._lock:
            self._cursor = 0
            self.state = "stopped"
            self.scenario_state = "idle"
            self.active_scenario = None
            self.virtual_clock = TRIGGER_TIME - timedelta(minutes=5)
            self.counters.clear()
            self.last_ingest_at.clear()
            return self.status()

    def reset_state(self) -> None:
        """Satisfy SimulatorResetHook protocol."""
        self.reset()

    def tick(self) -> dict:
        with self._lock:
            if self.state != "running":
                return self.status()
            if self._cursor >= len(self._baseline):
                self.state = "ready"
                self.scenario_state = "baseline_complete"
                self.virtual_clock = TRIGGER_TIME
                return self.status()
            group = self._baseline[self._cursor]
            self._emit_group(group.records)
            self._cursor += 1
            self.virtual_clock = group.timestamp + timedelta(seconds=settings.simulator_metric_interval_seconds)
            if self._cursor == len(self._baseline):
                self.state = "ready"
                self.scenario_state = "baseline_complete"
                self.virtual_clock = TRIGGER_TIME
            return self.status()

    def trigger(self, scenario_id: str) -> dict:
        if scenario_id not in {
            "gateway_rate_limit",
            "gateway_rate_limit_disabled",
            SCENARIO_KEY,
            SCENARIO_ID,
            TRACE_ID,
        }:
            raise KeyError(scenario_id)
        self._stop_worker()
        with self._lock:
            self.active_scenario = SCENARIO_KEY
            self.state = "triggering"
            self.scenario_state = "triggering"
            while self._cursor < len(self._baseline):
                group = self._baseline[self._cursor]
                self._emit_group(group.records)
                self._cursor += 1
                self.virtual_clock = group.timestamp + timedelta(seconds=settings.simulator_metric_interval_seconds)
            for group in scenario_groups():
                self._emit_group(group.records)
                self.virtual_clock = group.timestamp
            self.state = "completed"
            self.scenario_state = "completed"
            return self.status()

    def status(self) -> dict:
        with self._lock:
            topology = json.loads(TOPOLOGY_FIXTURE.read_text(encoding="utf-8"))
            source_health = []
            for source_id, source_type in SOURCE_TYPES.items():
                counts = dict(self.counters[source_id])
                source_health.append(
                    {
                        "source_id": source_id,
                        "source_type": source_type,
                        "status": "ready",
                        "last_ingest_at": self.last_ingest_at.get(source_id),
                        "accepted": counts["accepted"],
                        "collapsed": counts["collapsed"],
                        "quarantined": counts["quarantined"],
                        "fixture_version": None,
                    }
                )
            source_health.append(
                {
                    "source_id": TOPOLOGY_SOURCE,
                    "source_type": "topology",
                    "status": "ready",
                    "last_ingest_at": topology["generated_at"],
                    "accepted": 1,
                    "collapsed": 0,
                    "quarantined": 0,
                    "fixture_version": topology["version"],
                }
            )
            return {
                "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "state": self.state,
                "scenario_state": self.scenario_state,
                "scenario_id": self.active_scenario,
                "virtual_clock": self.virtual_clock.isoformat().replace("+00:00", "Z"),
                "seed": settings.simulator_seed,
                "metric_interval_seconds": settings.simulator_metric_interval_seconds,
                "baseline_ticks_emitted": self._cursor,
                "baseline_ticks_required": len(self._baseline),
                "sources": {source: dict(counts) for source, counts in self.counters.items()},
                "source_health": source_health,
            }

    def _emit_group(self, records: tuple[tuple[str, dict], ...]) -> None:
        ingest_group = getattr(self.ingestion, "ingest_group", None)
        outcomes = (
            ingest_group(records)
            if callable(ingest_group)
            else [self.ingestion.ingest(source, raw) for source, raw in records]
        )
        if len(outcomes) != len(records):
            raise RuntimeError("ingestion group returned the wrong number of outcomes")
        for (source, raw), outcome in zip(records, outcomes, strict=True):
            self.counters[source]["emitted"] += 1
            self.counters[source][outcome.status] += 1
            emitted_at = raw.get("emitted_at")
            if isinstance(emitted_at, str):
                self.last_ingest_at[source] = emitted_at

    def _run(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                state = self.state
            if state == "paused":
                self._stop_event.wait(SIMULATOR_REAL_TICK_SECONDS)
                continue
            if state != "running":
                return
            self.tick()
            self._stop_event.wait(SIMULATOR_REAL_TICK_SECONDS)

    def _start_worker(self) -> None:
        if not self.background or (self._worker and self._worker.is_alive()):
            return
        self._worker = threading.Thread(target=self._run, name="simulator-engine", daemon=True)
        self._worker.start()

    def _stop_worker(self) -> None:
        self._stop_event.set()
        worker = self._worker
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=1)
        self._worker = None


simulator_engine = SimulatorEngine()

# Register the simulator engine with the reset service
from app.orchestration.reset_service import reset_service
reset_service.register_simulator(simulator_engine)
