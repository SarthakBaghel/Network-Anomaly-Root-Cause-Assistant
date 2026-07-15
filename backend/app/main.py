from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Response, status

from app.api import events_router, incidents_router, simulator_router, topology_router
from app.readiness import readiness_report

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """Startup: load topology fixture into DB and seed historical incidents.

    Blueprint §4.1: startup validates settings, DB connectivity, catalogues,
    topology fixture, and fixture schema versions.
    """
    _startup()
    yield
    # Shutdown — nothing to do for the synchronous prototype


def _startup() -> None:
    """Idempotent startup: loads topology + seeds history if not already present."""
    from app.db.session import session_scope
    from app.incidents import incident_manager
    from app.orchestration.orchestrator import orchestrator
    from app.orchestration.reset_service import (
        _reload_topology,
        _seed_historical_incident,
    )
    from app.db import models
    from sqlalchemy import select

    try:
        with session_scope() as session:
            # Only reload if entities table is empty (idempotent)
            count = session.execute(
                select(models.Entity)
            ).first()
            if count is None:
                logger.info("Startup: loading topology fixture into DB")
                _reload_topology(session)
                logger.info("Startup: seeding historical incidents")
                _seed_historical_incident(session)
            else:
                logger.debug("Startup: topology already loaded, skipping")
        orchestrator.register_incident_manager(incident_manager)
    except Exception:
        logger.exception(
            "Startup: failed to load topology or seed history. "
            "Run 'python scripts/seed_demo.py' and check alembic migrations."
        )
        raise


app = FastAPI(
    title="Network Anomaly Root-Cause Assistant",
    version="0.1.0",
    description="Milestone-0 contract API; feature routes are owner-labelled stubs.",
    lifespan=lifespan,
)


@app.get("/api/v1/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/ready", tags=["system"])
def ready(response: Response) -> dict[str, Any]:
    is_ready, components = readiness_report()
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if is_ready else "not_ready",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "components": components,
    }


for router in (events_router, simulator_router, incidents_router, topology_router):
    app.include_router(router, prefix="/api/v1")
