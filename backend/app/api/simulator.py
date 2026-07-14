from typing import Any

from fastapi import APIRouter

from .stubs import feature_not_implemented


router = APIRouter(prefix="/simulator", tags=["simulator"])


@router.post("/start", response_model=dict[str, Any])
def start() -> dict[str, Any]:
    feature_not_implemented("Person 3")


@router.post("/stop", response_model=dict[str, Any])
def stop() -> dict[str, Any]:
    feature_not_implemented("Person 3")


@router.post("/reset", response_model=dict[str, Any])
def reset() -> dict[str, Any]:
    """Execute the full demo reset sequence (blueprint §5.2, P1-22).

    Stops the simulator, clears demo rows, reloads topology,
    re-seeds history, resets the simulator clock, and writes DEMO_RESET audit.
    """
    from app.db.session import session_scope
    from app.orchestration import reset_service

    with session_scope() as session:
        result = reset_service.execute(session)
    return result


@router.post("/scenarios/{scenario_id}/trigger", response_model=dict[str, Any])
def trigger(scenario_id: str) -> dict[str, Any]:
    del scenario_id
    feature_not_implemented("Person 3")


@router.get("/status", response_model=dict[str, Any])
def status() -> dict[str, Any]:
    feature_not_implemented("Person 3")

