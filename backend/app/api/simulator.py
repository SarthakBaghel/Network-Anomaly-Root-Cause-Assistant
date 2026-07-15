from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from app.contracts import (
    SimulatorMutationResponse,
    SimulatorResetResponse,
    SimulatorScenario,
    SimulatorScenarioListResponse,
    SimulatorStatusResponse,
)
from app.simulator import simulator_engine
from app.simulator.engine import SimulatorStateError
from app.simulator.scenario_catalogue import list_scenarios
from .error_responses import ERROR_RESPONSES
import uuid

router = APIRouter(prefix="/simulator", tags=["simulator"], responses=ERROR_RESPONSES)


def _mutation(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "request_id": f"req_{uuid.uuid4().hex}"}


@router.post("/start", response_model=SimulatorMutationResponse)
def start() -> dict[str, Any]:
    try:
        return _mutation(simulator_engine.start())
    except SimulatorStateError as exc:
        raise HTTPException(
            409, detail={"code": "SCENARIO_STATE_CONFLICT", "message": str(exc)}
        ) from exc


@router.post("/stop", response_model=SimulatorMutationResponse)
def stop() -> dict[str, Any]:
    if simulator_engine.status()["state"] != "running":
        raise HTTPException(
            409,
            detail={
                "code": "SCENARIO_STATE_CONFLICT",
                "message": "only a running simulator can be stopped",
            },
        )
    return _mutation(simulator_engine.stop())


@router.post("/reset", response_model=SimulatorResetResponse)
def reset() -> SimulatorResetResponse:
    """Execute the full demo reset sequence (blueprint §5.2, P1-22).

    Stops the simulator, clears demo rows, reloads topology,
    re-seeds history, resets the simulator clock, and writes DEMO_RESET audit.
    """
    from app.db.session import session_scope
    from app.orchestration import reset_service

    # Dynamically register the current simulator_engine reference to handle test monkeypatching
    reset_service.register_simulator(simulator_engine)

    with session_scope() as session:
        result = reset_service.execute(session)

    return SimulatorResetResponse(
        **simulator_engine.status(),
        request_id=f"req_{uuid.uuid4().hex}",
        reset_audit_id=result["audit_id"],
    )


@router.post("/scenarios/{scenario_id}/trigger", response_model=SimulatorMutationResponse)
def trigger(scenario_id: str) -> dict[str, Any]:
    try:
        return _mutation(simulator_engine.trigger(scenario_id))
    except KeyError as exc:
        raise HTTPException(
            404, detail={"code": "NOT_FOUND", "message": "Unknown simulator scenario"}
        ) from exc
    except SimulatorStateError as exc:
        raise HTTPException(
            409, detail={"code": "SCENARIO_STATE_CONFLICT", "message": str(exc)}
        ) from exc


@router.get("/scenarios", response_model=SimulatorScenarioListResponse)
def scenarios() -> SimulatorScenarioListResponse:
    return SimulatorScenarioListResponse(
        generated_at=datetime.now(timezone.utc),
        items=[
            SimulatorScenario(
                scenario_id=item.scenario_id,
                title=item.title,
                description=item.description,
                affected_entity_ids=list(item.affected_entity_ids),
                duration_seconds=item.duration_seconds,
                expected_signals=list(item.expected_signals),
                difficulty=item.difficulty,
                reference_datasets=list(item.reference_datasets),
                transformation_version=item.transformation_version,
                quality_flag=item.quality_flag,
            )
            for item in list_scenarios()
        ],
    )


@router.get("/status", response_model=SimulatorStatusResponse)
def status() -> dict[str, Any]:
    return simulator_engine.status()
