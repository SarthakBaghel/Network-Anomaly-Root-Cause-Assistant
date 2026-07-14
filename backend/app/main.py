from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Response, status

from app.api import events_router, incidents_router, simulator_router, topology_router
from app.readiness import readiness_report


app = FastAPI(
    title="Network Anomaly Root-Cause Assistant",
    version="0.1.0",
    description="Milestone-0 contract API; feature routes are owner-labelled stubs.",
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

