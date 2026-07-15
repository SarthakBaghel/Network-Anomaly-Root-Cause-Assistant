from typing import Any

from fastapi import APIRouter, HTTPException

from app.simulator import simulator_engine
from app.simulator.engine import SimulatorStateError

router = APIRouter(prefix="/simulator", tags=["simulator"])


@router.post("/start", response_model=dict[str, Any])
def start() -> dict[str, Any]:
    return simulator_engine.start()


@router.post("/stop", response_model=dict[str, Any])
def stop() -> dict[str, Any]:
    return simulator_engine.stop()


@router.post("/reset", response_model=dict[str, Any])
def reset() -> dict[str, Any]:
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

    # Merge simulator status to satisfy test expectations
    result.update(simulator_engine.status())
    return result


@router.post("/scenarios/{scenario_id}/trigger", response_model=dict[str, Any])
def trigger(scenario_id: str) -> dict[str, Any]:
    try:
        return simulator_engine.trigger(scenario_id)
    except KeyError as exc:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Unknown simulator scenario"}) from exc
    except SimulatorStateError as exc:
        raise HTTPException(409, detail={"code": "SCENARIO_STATE_CONFLICT", "message": str(exc)}) from exc


@router.get("/status", response_model=dict[str, Any])
def status() -> dict[str, Any]:
    return simulator_engine.status()

