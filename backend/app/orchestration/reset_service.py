"""
ResetService — Person 1 (blueprint §5.2, P1-22).

POST /simulator/reset sequence (blueprint §5.2):
  1. Call P3's simulator stop hook (P3 owns emitter lifecycle)
  2. Acquire the analysis lock
  3. Clear demo-generated rows in FK-safe order
     (leaves: entities, topology_edges, historical_incidents)
  4. Reload topology fixture (via readiness catalogue loader)
  5. Re-seed historical_incidents
  6. Call P3's deterministic clock/state reset hook
  7. Write one DEMO_RESET audit entry
  8. Release the lock

Ownership split: P3 owns emitter state and reset hook.
Person 1 owns the cross-domain transaction, lock, DB clearing, and API wiring.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.audit.contracts import AuditWrite
from app.audit.service import audit_service
from app.db import models
from app.orchestration.orchestrator import AnalysisOrchestrator

logger = logging.getLogger(__name__)


@runtime_checkable
class SimulatorResetHook(Protocol):
    """Implemented by app.simulator (Person 3)."""

    def stop(self) -> None:
        """Stop all emitters (idempotent)."""
        ...

    def reset_state(self) -> None:
        """Reset virtual clock and random seed to SIMULATOR_SEED defaults."""
        ...


class ResetService:
    """Cross-domain demo reset.

    Injected with the orchestrator so it can acquire the same analysis lock.
    The simulator hook is optional; if None, emitter state is not touched
    (safe for testing without a running simulator).
    """

    def __init__(
        self,
        orchestrator: AnalysisOrchestrator,
        simulator_hook: SimulatorResetHook | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._simulator_hook = simulator_hook

    def register_simulator(self, hook: SimulatorResetHook) -> None:
        """P3 calls this at startup to wire the simulator state into reset."""
        self._simulator_hook = hook

    # ------------------------------------------------------------------
    # Main reset entry point
    # ------------------------------------------------------------------

    def execute(self, session: Session) -> dict[str, Any]:
        """Run the full demo reset.

        Called by POST /api/v1/simulator/reset.
        Returns a summary dict with a DEMO_RESET audit ID.
        """
        # Step 1 — Stop emitters (P3 owns; non-blocking for us if hook absent)
        if self._simulator_hook is not None:
            try:
                self._simulator_hook.stop()
            except Exception:
                logger.exception("Simulator stop hook raised; proceeding with reset")

        # Step 2 — Acquire the analysis lock (same lock the orchestrator uses)
        with self._orchestrator._lock:
            return self._locked_reset(session)

    def _locked_reset(self, session: Session) -> dict[str, Any]:
        """All DB work happens inside the analysis lock."""
        # Step 3 — Clear demo-generated rows in FK-safe order
        _clear_demo_rows(session)

        # Step 4 — Reload topology fixture into DB (entities + edges)
        _reload_topology(session)

        # Step 5 — Re-seed historical_incidents
        _seed_historical_incident(session)

        # Flush before writing the audit entry so all FKs resolve
        session.flush()

        # Step 7 — Write the DEMO_RESET audit entry
        reset_at = datetime.now(tz=timezone.utc)
        request_id = f"reset:{reset_at.isoformat()}"
        audit_row = audit_service.append(
            AuditWrite(
                action="DEMO_RESET",
                actor_type="system",
                actor_id="reset_service",
                object_type="system",
                object_id="demo",
                request_id=request_id,
                reason_codes=["DETERMINISTIC_DEMO_RESET"],
                metadata={"reset_at": reset_at.isoformat()},
            ),
            session,
            timestamp=reset_at,
        )
        audit_id = audit_row.id
        session.flush()

        # Step 6 — Reset simulator state (after DB is clean)
        if self._simulator_hook is not None:
            try:
                self._simulator_hook.reset_state()
            except Exception:
                logger.exception("Simulator reset_state hook raised; DB reset succeeded")

        logger.info("Demo reset complete — audit entry %s written", audit_id)
        return {"status": "reset", "audit_id": audit_id}


# ---------------------------------------------------------------------------
# Helpers — private to this module
# ---------------------------------------------------------------------------


def _clear_demo_rows(session: Session) -> None:
    """Delete all demo-generated rows in FK-safe order.

    Preserved tables: entities, topology_edges, historical_incidents.
    This is the ONLY allowed bulk-purge path (blueprint §8.2).
    """
    from sqlalchemy.exc import OperationalError

    # Disable FK checks temporarily for cascade safety
    session.execute(text("PRAGMA foreign_keys=OFF"))
    try:
        # Order: most dependent first
        session.execute(delete(models.AuditLog))
        session.execute(delete(models.Review))
        session.execute(delete(models.Explanation))
        session.execute(delete(models.PlaybookRecommendation))
        session.execute(delete(models.Evidence))
        session.execute(delete(models.Hypothesis))
        session.execute(delete(models.AnalysisRun))
        session.execute(delete(models.IncidentEventEvaluation))
        session.execute(delete(models.IncidentEvent))
        session.execute(delete(models.Incident))
        session.execute(delete(models.Anomaly))
        try:
            with session.begin_nested():
                session.execute(delete(models.EwmaBaseline))  # Adaptive baselines reset with demo state
        except OperationalError:
            # Table absent in pre-migration DB — safe to skip during test/dev
            pass
        session.execute(delete(models.CollapsedEventGroup))
        session.execute(delete(models.Event))
        session.execute(delete(models.QuarantinedEvent))
        session.flush()
    finally:
        session.execute(text("PRAGMA foreign_keys=ON"))




def _reload_topology(session: Session) -> None:
    """Reload entities and topology edges from the fixture file.

    Drops and re-inserts so any fixture changes are picked up.
    topology_edges reference entities, so entities must be inserted first.
    """
    import json
    from pathlib import Path

    topo_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "topology.json"
    )
    topo = json.loads(topo_path.read_text(encoding="utf-8"))

    # Validate frozen entity IDs
    node_ids = {n["id"] for n in topo.get("nodes", [])}
    required = {
        "api-gateway-01",
        "checkout-api-01",
        "payment-api-01",
        "payment-db-01",
        "auth-api-01",
    }
    if not required.issubset(node_ids):
        raise RuntimeError(
            f"topology.json is missing required entity IDs: {required - node_ids}"
        )

    # Re-insert entities
    session.execute(delete(models.TopologyEdge))
    session.execute(delete(models.Entity))
    session.flush()

    for node in topo["nodes"]:
        session.add(
            models.Entity(
                id=node["id"],
                name=node.get("name", node["id"]),
                entity_type=node.get("entity_type", "service"),
                service=node.get("service", node["id"]),
                criticality=node.get("criticality", "normal"),
                metadata_json=node.get("metadata", {}),
            )
        )
    session.flush()

    # Re-insert edges
    valid_relations = {"depends_on", "sends_traffic_to"}
    for i, edge in enumerate(topo.get("edges", [])):
        if edge["source"] == edge["target"]:
            raise RuntimeError(f"topology.json contains self-edge: {edge['source']}")
        if edge["relation_type"] not in valid_relations:
            raise RuntimeError(
                f"topology.json edge has unsupported relation_type: {edge['relation_type']}"
            )
        session.add(
            models.TopologyEdge(
                id=f"edge_{i:04d}",
                source_entity_id=edge["source"],
                target_entity_id=edge["target"],
                relation_type=edge["relation_type"],
                relationship=edge.get("relationship", edge["relation_type"]),
                active_from=None,
                active_to=None,
            )
        )
    session.flush()


def _seed_historical_incident(session: Session) -> None:
    """Re-seed the one deterministic historical incident (blueprint P1-10).

    Same confirmed cause as the golden scenario, half of the fingerprint
    features → historical_similarity = 0.5 → frozen score 92.1 preserved.
    """
    session.execute(delete(models.HistoricalIncident))
    session.flush()
    session.add(
        models.HistoricalIncident(
            id="hist_gateway_rate_limit_001",
            fingerprint="gateway-rate-limit-half-feature-match",
            confirmed_cause="configuration_regression",
            summary=(
                "Prior gateway incident confirmed after a rate-limit "
                "configuration regression."
            ),
            feature_vector={
                "entity_type": "gateway",
                "change_type": "rate_limit.enabled",
                "forwarded_traffic_spike": True,
                "same_confirmed_cause": True,
                "similarity": 0.5,
            },
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

reset_service = ResetService(
    orchestrator=__import__(
        "app.orchestration.orchestrator", fromlist=["orchestrator"]
    ).orchestrator
)
