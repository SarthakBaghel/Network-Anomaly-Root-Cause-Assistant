from typing import Any

from fastapi import APIRouter

from app.contracts import TopologySnapshot

from .stubs import feature_not_implemented


router = APIRouter(prefix="/topology", tags=["topology"])


@router.get("", response_model=TopologySnapshot)
def topology() -> TopologySnapshot:
    feature_not_implemented("Person 4")


@router.get("/path", response_model=dict[str, Any])
def path() -> dict[str, Any]:
    feature_not_implemented("Person 4")


@router.get("/blast-radius/{entity_id}", response_model=dict[str, Any])
def blast_radius(entity_id: str) -> dict[str, Any]:
    del entity_id
    feature_not_implemented("Person 4")

