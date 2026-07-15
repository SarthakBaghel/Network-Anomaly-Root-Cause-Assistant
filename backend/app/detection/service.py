"""
DetectorService and DetectionPublisher — Phase-3 detection boundary.

This module orchestrates all registered detectors and provides them with
a fully populated DetectionContext that includes:

  1. history         — metric/log events in the rolling window (existing)
  2. safety_thresholds — loaded from network_profile.json (existing)
  3. signal_aliases  — proxy mappings from network_profile.json (existing)
  4. ewma_state      — current canonical signal baseline from EwmaStateStore (NEW)
  5. topology        — TopologyView built from topology_edges table (NEW)
  6. recent_anomalies — last N actionable anomalies for cascade detection (NEW)

BLUEPRINT compliance:
  §11.4: Every detector sees a consistent DetectionContext snapshot
  §12.2: TopologyView provides typed-edge BFS for cascade traversal
  §3.2:  EWMA alpha is a constant in ewma_detector.py — NOT in context
  §3.3.4: Signal aliases exposed in context for proxy resolution
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.contracts import AnomalyRecord, CanonicalEvent
from app.db.models import Anomaly, Event
from app.detection.alert_severity import AlertSeverityDetector
from app.detection.config_change import ConfigChangeMarker
from app.detection.detector import DetectionContext, Detector
from app.detection.ewma_detector import EwmaDetector
from app.detection.ewma_store import ewma_store
from app.detection.log_rule import LogRuleDetector
from app.detection.rolling_zscore import RollingZscoreDetector
from app.detection.reference_threshold import ReferenceThresholdDetector
from app.detection.trace_anomaly import TraceLatencyDetector, TraceStructureDetector
from app.detection.topology_cascade import TopologyCascadeDetector
from app.detection.topology_view import TopologyView

# Number of recent actionable anomalies to load for cascade correlation
# (context_only anomalies excluded — they cannot trigger further cascades)
RECENT_ANOMALY_WINDOW_SECONDS = settings.detector_window_seconds * 2

DETECTORS: tuple[Detector, ...] = (
    ReferenceThresholdDetector(),
    RollingZscoreDetector(),
    EwmaDetector(),
    LogRuleDetector(),
    AlertSeverityDetector(),
    ConfigChangeMarker(),
    TraceLatencyDetector(),
    TraceStructureDetector(),
    TopologyCascadeDetector(),
)


def _build_context(
    event: CanonicalEvent,
    session: Session,
    *,
    topology: TopologyView | None = None,
) -> DetectionContext:
    """Build a fully-populated DetectionContext for a single event evaluation.

    Includes EWMA state, topology graph, and recent anomalies in addition
    to the standard rolling history window.

    The topology is passed in pre-built (built once per batch) to avoid
    re-querying the DB for every event in a batch.
    """
    from app.ingestion.pipeline import event_to_contract

    # 1. Rolling history window (unchanged from original)
    history_rows = session.scalars(
        select(Event)
        .where(
            Event.timestamp
            >= event.timestamp - timedelta(seconds=settings.detector_window_seconds),
            Event.timestamp < event.timestamp,
        )
        .order_by(Event.timestamp, Event.id)
    )
    history = [event_to_contract(row) for row in history_rows]

    ctx = DetectionContext(history=history)

    # 2. EWMA state — load the canonical state for the signal being evaluated.
    #    Alias resolution must happen here as well as in EwmaDetector; otherwise
    #    proxy events repeatedly cold-start instead of resuming persisted state.
    ewma_state: dict[str, dict] = {}
    if event.signal_name is not None:
        effective_signal = ctx.signal_aliases.get(event.signal_name, event.signal_name)
        key = f"{event.entity_id}:{effective_signal}"
        stored = ewma_store.get(event.entity_id, effective_signal, session)
        if stored is not None:
            ewma_state[key] = dict(stored)

    # 3. Recent actionable anomalies for cascade detection
    #    Only non-context_only anomalies can trigger downstream cascade signals
    recent_anomaly_rows = session.scalars(
        select(Anomaly)
        .where(
            Anomaly.window_end
            >= event.timestamp - timedelta(seconds=RECENT_ANOMALY_WINDOW_SECONDS),
            Anomaly.context_only == False,  # noqa: E712
        )
        .order_by(Anomaly.window_end.desc())
        .limit(50)
    ).all()

    # Build lightweight anomaly objects for the cascade detector
    recent_anomalies = [
        _RecentAnomaly(
            entity_id=_extract_entity_id(row, session),
            anomaly_id=row.id,
            anomaly_type=row.type,
            score=row.score,
        )
        for row in recent_anomaly_rows
        if _extract_entity_id(row, session) is not None
    ]

    # 4. Assemble DetectionContext (frozen dataclass — inject extras via __setattr__)
    object.__setattr__(ctx, "ewma_state", ewma_state)
    object.__setattr__(ctx, "_ewma_updates", {})
    object.__setattr__(ctx, "topology", topology)
    object.__setattr__(ctx, "recent_anomalies", recent_anomalies)
    return ctx


class _RecentAnomaly:
    """Lightweight anomaly descriptor consumed by TopologyCascadeDetector."""

    __slots__ = ("entity_id", "anomaly_id", "anomaly_type", "score")

    def __init__(
        self,
        entity_id: str | None,
        anomaly_id: str,
        anomaly_type: str,
        score: float,
    ) -> None:
        self.entity_id = entity_id
        self.anomaly_id = anomaly_id
        self.anomaly_type = anomaly_type
        self.score = score


def _extract_entity_id(anomaly_row: Anomaly, session: Session) -> str | None:
    """Resolve entity_id from an Anomaly row via its associated Event."""
    event_row = session.get(Event, anomaly_row.event_id)
    return event_row.entity_id if event_row is not None else None


def _anomaly_row(anomaly: AnomalyRecord) -> Anomaly:
    """Map the P3 detector contract to an uncommitted P1-owned ORM row."""
    return Anomaly(
        id=anomaly.anomaly_id,
        event_id=anomaly.event_id,
        detector_id=anomaly.detector_id,
        type=anomaly.anomaly_type,
        detected_at=anomaly.detected_at,
        score=anomaly.score,
        threshold=anomaly.threshold,
        context_only=anomaly.context_only,
        can_open_incident=anomaly.can_open_incident,
        window_start=anomaly.window_start,
        window_end=anomaly.window_end,
        features=anomaly.features,
        explanation=anomaly.explanation,
    )


def _persist_anomaly(session: Session, anomaly: AnomalyRecord) -> Anomaly | None:
    """Legacy standalone publisher persistence; the orchestrator does not use it."""
    exists = session.scalar(
        select(Anomaly.id).where(
            Anomaly.event_id == anomaly.event_id,
            Anomaly.detector_id == anomaly.detector_id,
        )
    )
    if exists is not None:
        return None
    row = _anomaly_row(anomaly)
    session.add(row)
    return row


def _flush_ewma_updates(ctx: DetectionContext, session: Session) -> None:
    """Flush any EWMA state updates that the EwmaDetector wrote into context."""
    updates: dict = getattr(ctx, "_ewma_updates", {})
    for key, (entity_id, signal_name, state) in updates.items():
        ewma_store.put(entity_id, signal_name, state, session)


class DetectionPublisher:
    """Synchronous Phase-3 boundary invoked after accepted-event persistence.

    Builds a topology view once per batch (not per event) for efficiency.
    Flushes EWMA state to DB after each batch.
    """

    def __init__(self, session: Session, detectors: tuple[Detector, ...] = DETECTORS) -> None:
        self.session = session
        self.detectors = detectors
        self._topology: TopologyView | None = None

    def _get_topology(self) -> TopologyView:
        """Build topology view once per publisher instance (one per request)."""
        if self._topology is None:
            try:
                self._topology = TopologyView.build_for_session(self.session)
            except Exception:
                self._topology = TopologyView([])  # Graceful degradation
        return self._topology

    def publish(self, event: CanonicalEvent) -> None:
        topo = self._get_topology()
        ctx = _build_context(event, self.session, topology=topo)
        self._evaluate_and_persist(event, ctx)
        _flush_ewma_updates(ctx, self.session)
        ewma_store.flush(self.session)

    def publish_batch(self, events: list[CanonicalEvent]) -> None:
        topo = self._get_topology()
        for event in sorted(events, key=lambda item: (item.timestamp, item.event_id)):
            ctx = _build_context(event, self.session, topology=topo)
            self._evaluate_and_persist(event, ctx)
            _flush_ewma_updates(ctx, self.session)
        ewma_store.flush(self.session)

    def _evaluate_and_persist(
        self, event: CanonicalEvent, ctx: DetectionContext
    ) -> list[AnomalyRecord]:
        records: list[AnomalyRecord] = []
        for detector in self.detectors:
            for anomaly in detector.evaluate(event, ctx):
                row = _persist_anomaly(self.session, anomaly)
                if row is not None:
                    records.append(anomaly)
        self.session.flush()
        return records


class DetectorService:
    """Implement DetectorProtocol for the AnalysisOrchestrator.

    Used in run_anomaly_detection.py and unit tests. Builds topology view
    once per evaluate_event call. EWMA state is flushed after each event
    for simplicity (vs. batching in DetectionPublisher).
    """

    def __init__(self, detectors: tuple[Detector, ...] = DETECTORS) -> None:
        self.detectors = detectors

    def evaluate_event(self, event: Event, session: Session) -> list[Anomaly]:
        from app.ingestion.pipeline import event_to_contract

        contract_event = event_to_contract(event)

        # Build topology view for cascade detection
        try:
            topology = TopologyView.build_for_session(session)
        except Exception:
            topology = TopologyView([])

        ctx = _build_context(contract_event, session, topology=topology)

        records: list[Anomaly] = []
        for detector in self.detectors:
            for anomaly in detector.evaluate(contract_event, ctx):
                records.append(_anomaly_row(anomaly))

        _flush_ewma_updates(ctx, session)
        ewma_store.flush(session)

        return records
