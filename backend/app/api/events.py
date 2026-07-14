from typing import Any

from fastapi import APIRouter

from app.contracts import CanonicalEvent

from .stubs import feature_not_implemented


router = APIRouter(tags=["events"])


@router.post("/events", response_model=dict[str, Any])
def ingest_event(_event: CanonicalEvent) -> dict[str, Any]:
    feature_not_implemented("Person 3")


@router.post("/events/batch", response_model=dict[str, Any])
def ingest_batch(_events: list[CanonicalEvent]) -> dict[str, Any]:
    feature_not_implemented("Person 3")


@router.get("/events", response_model=list[CanonicalEvent])
def list_events() -> list[CanonicalEvent]:
    feature_not_implemented("Person 3")


@router.get("/events/{event_id}", response_model=CanonicalEvent)
def get_event(event_id: str) -> CanonicalEvent:
    del event_id
    feature_not_implemented("Person 3")


@router.get("/quarantine", response_model=dict[str, Any])
def list_quarantine() -> dict[str, Any]:
    feature_not_implemented("Person 3")

