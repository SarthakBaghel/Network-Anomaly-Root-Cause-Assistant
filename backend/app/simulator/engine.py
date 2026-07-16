import threading
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.simulator.ingestion import IngestionSink, PersistentIngestionSink
from app.simulator.scenario_catalogue import groups_for_scenario
from app.simulator.timeline import TRIGGER_TIME, baseline_groups

SIMULATOR_REAL_TICK_SECONDS = 0.05
SOURCE_TYPES = {
    "simulator.prometheus": "metrics",
    "simulator.syslog": "logs",
    "simulator.alertmanager": "alerts",
    "simulator.config_audit": "config_changes",
    "simulator.trace": "traces",
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
        self.counters: defaultdict[str, dict[str, int]] = defaultdict(
            lambda: {"emitted": 0, "accepted": 0, "collapsed": 0, "quarantined": 0}
        )
        self.last_ingest_at: dict[str, str] = {}
        self.last_reset_at: datetime | None = None

    def start(self) -> dict:
        with self._lock:
            if self.last_reset_at is None:
                raise SimulatorStateError("reset simulator data before running the baseline")
            if self.state == "running":
                return self.status()
            if self.active_scenario is not None:
                raise SimulatorStateError(
                    "reset the simulator before starting a completed scenario again"
                )
            if self.state == "ready" or self._cursor >= len(self._baseline):
                raise SimulatorStateError(
                    "baseline is already complete; reset before running it again"
                )
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
            self.last_reset_at = datetime.now(timezone.utc)
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
            self.virtual_clock = group.timestamp + timedelta(
                seconds=settings.simulator_metric_interval_seconds
            )
            if self._cursor == len(self._baseline):
                self.state = "ready"
                self.scenario_state = "baseline_complete"
                self.virtual_clock = TRIGGER_TIME
            return self.status()

    def complete_baseline(self) -> dict:
        """Synchronously finish a baseline for deterministic non-background callers."""

        while True:
            current = self.status()
            if current["state"] != "running":
                return current
            self.tick()

    def trigger(self, scenario_id: str) -> dict:
        resolved_scenario_id, groups = groups_for_scenario(scenario_id)
        with self._lock:
            if self.state != "ready" or self.scenario_state != "baseline_complete":
                raise SimulatorStateError("complete the baseline before triggering a scenario")
            if self.active_scenario is not None:
                raise SimulatorStateError("another simulator scenario is already active")
        self._stop_worker()
        with self._lock:
            self.active_scenario = resolved_scenario_id
            self.state = "triggering"
            self.scenario_state = "triggering"
        # Ingestion can include RCA generation through local Ollama. Do not
        # hold the simulator state lock during that external work: status
        # requests must remain responsive while the trigger is processing.
        for group in groups:
            self._emit_group(group.records)
            with self._lock:
                self.virtual_clock = group.timestamp
        with self._lock:
            self.state = "completed"
            self.scenario_state = "completed"
            return self.status()

    def status(self) -> dict:
        with self._lock:
            topology = json.loads(TOPOLOGY_FIXTURE.read_text(encoding="utf-8"))
            source_health = []
            for source_id, source_type in SOURCE_TYPES.items():
                counts = dict(self.counters[source_id])
                last_ingest = self.last_ingest_at.get(source_id)
                if counts["quarantined"] > 0:
                    health_status = "quarantined"
                elif last_ingest is None:
                    health_status = "offline"
                else:
                    observed_at = datetime.fromisoformat(last_ingest.replace("Z", "+00:00"))
                    lag = self.virtual_clock - observed_at
                    health_status = "delayed" if lag > timedelta(minutes=2) else "healthy"
                source_health.append(
                    {
                        "source_id": source_id,
                        "source_type": source_type,
                        "status": health_status,
                        "last_ingest_at": last_ingest,
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
                    "status": "healthy",
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
                "last_reset_at": (
                    self.last_reset_at.isoformat().replace("+00:00", "Z")
                    if self.last_reset_at is not None
                    else None
                ),
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
        with self._lock:
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
from app.orchestration.reset_service import reset_service  # noqa: E402

reset_service.register_simulator(simulator_engine)
