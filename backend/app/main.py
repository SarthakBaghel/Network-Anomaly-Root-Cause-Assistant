from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    assistant_router,
    events_router,
    incidents_router,
    simulator_router,
    topology_router,
)
from app.contracts import ErrorBody, ErrorDetail, ErrorEnvelope, HealthResponse, ReadinessResponse
from app.readiness import catalogue_status, readiness_report

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
    from app.orchestration.reset_service import (
        _reload_topology,
        _seed_historical_incident,
    )
    from app.db import models
    from sqlalchemy import select

    # Register production components through the frozen orchestration boundaries.
    from app.orchestration.orchestrator import orchestrator
    from app.detection.service import DetectorService
    from app.incidents import incident_manager
    from app.orchestration.rca_adapter import RcaAnalysisAdapter
    from app.rca.analysis_engine import AnalysisEngine

    orchestrator.register_detector(DetectorService())
    orchestrator.register_incident_manager(incident_manager)
    orchestrator.register_analysis_engine(RcaAnalysisAdapter(AnalysisEngine()))

    try:
        catalogue_status()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:4173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
    expose_headers=["Content-Disposition", "X-Analysis-Run-ID"],
)


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = str(detail.get("code", "HTTP_ERROR"))
    message = str(detail.get("message", exc.detail if isinstance(exc.detail, str) else "Request failed"))
    raw_details = detail.get("details", [])
    details = []
    if isinstance(raw_details, list):
        for item in raw_details:
            if isinstance(item, dict) and item.get("reason_code"):
                details.append(ErrorDetail.model_validate(item))
    body = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error.get("loc", ())),
            reason_code=str(error.get("type", "VALIDATION_ERROR")).upper(),
        )
        for error in exc.errors()
    ]
    body = ErrorEnvelope(
        error=ErrorBody(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
        )
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


@app.get("/api/v1/health", tags=["system"], response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get(
    "/api/v1/ready",
    tags=["system"],
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(response: Response) -> ReadinessResponse:
    is_ready, components = readiness_report()
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        generated_at=datetime.now(timezone.utc),
        components=components,
    )


for router in (
    assistant_router,
    events_router,
    simulator_router,
    incidents_router,
    topology_router,
):
    app.include_router(router, prefix="/api/v1")
