import threading
from collections import defaultdict
from datetime import timedelta

from app.config import settings
from app.simulator.ingestion import IngestionSink, PersistentIngestionSink
from app.simulator.timeline import SCENARIO_ID, TRACE_ID, TRIGGER_TIME, baseline_groups, scenario_groups

SIMULATOR_REAL_TICK_SECONDS = 0.05


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
            return self.status()

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
        if scenario_id not in {"gateway_rate_limit", SCENARIO_ID, TRACE_ID}:
            raise KeyError(scenario_id)
        self._stop_worker()
        with self._lock:
            self.active_scenario = SCENARIO_ID
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
            return {
                "state": self.state,
                "scenario_state": self.scenario_state,
                "scenario_id": self.active_scenario,
                "virtual_clock": self.virtual_clock.isoformat().replace("+00:00", "Z"),
                "seed": settings.simulator_seed,
                "metric_interval_seconds": settings.simulator_metric_interval_seconds,
                "baseline_ticks_emitted": self._cursor,
                "baseline_ticks_required": len(self._baseline),
                "sources": {source: dict(counts) for source, counts in self.counters.items()},
            }

    def _emit_group(self, records: tuple[tuple[str, dict], ...]) -> None:
        for source, raw in records:
            outcome = self.ingestion.ingest(source, raw)
            self.counters[source]["emitted"] += 1
            self.counters[source][outcome.status] += 1

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
