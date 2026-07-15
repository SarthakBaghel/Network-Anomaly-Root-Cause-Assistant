from typing import Any

from fastapi import APIRouter, HTTPException

from app.contracts import SimulatorResetResponse, SimulatorStatusResponse
from app.simulator import simulator_engine
from app.simulator.engine import SimulatorStateError

router = APIRouter(prefix="/simulator", tags=["simulator"])


@router.post("/start", response_model=SimulatorStatusResponse)
def start() -> dict[str, Any]:
    return simulator_engine.start()


@router.post("/stop", response_model=SimulatorStatusResponse)
def stop() -> dict[str, Any]:
    return simulator_engine.stop()


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
        reset_audit_id=result["audit_id"],
    )


@router.post("/scenarios/{scenario_id}/trigger", response_model=SimulatorStatusResponse)
def trigger(scenario_id: str) -> dict[str, Any]:
    try:
        return simulator_engine.trigger(scenario_id)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Unknown simulator scenario"}) from exc
    except SimulatorStateError as exc:
        raise HTTPException(409, detail={"code": "SCENARIO_STATE_CONFLICT", "message": str(exc)}) from exc


@router.get("/status", response_model=SimulatorStatusResponse)
def status() -> dict[str, Any]:
    return simulator_engine.status()
