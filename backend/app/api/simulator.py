from typing import Any

from fastapi import APIRouter, HTTPException

from app.contracts import SimulatorMutationResponse, SimulatorResetResponse, SimulatorStatusResponse
from app.simulator import simulator_engine
from app.simulator.engine import SimulatorStateError
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
        raise HTTPException(409, detail={"code": "SCENARIO_STATE_CONFLICT", "message": str(exc)}) from exc


@router.post("/stop", response_model=SimulatorMutationResponse)
def stop() -> dict[str, Any]:
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
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Unknown simulator scenario"}) from exc
    except SimulatorStateError as exc:
        raise HTTPException(409, detail={"code": "SCENARIO_STATE_CONFLICT", "message": str(exc)}) from exc


@router.get("/status", response_model=SimulatorStatusResponse)
def status() -> dict[str, Any]:
    return simulator_engine.status()
