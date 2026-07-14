from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.contracts import CanonicalEvent
from app.db.models import Event, QuarantinedEvent
from app.db.session import get_session
from app.ingestion.pipeline import IngestionPipeline, IngestionResult, event_to_contract


router = APIRouter(tags=["events"])
UTC = timezone.utc


class RawEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1)
    record: Any


class BatchEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[RawEventRequest] = Field(min_length=1, max_length=settings.event_batch_max_items)


def _result(result: IngestionResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "event_id": result.event_id,
        "reason_codes": result.reason_codes,
        "collapsed_group_id": result.collapsed_group_id,
    }


@router.post("/events", response_model=dict[str, Any])
def ingest_event(request: RawEventRequest, response: Response, session: Session = Depends(get_session)) -> dict[str, Any]:
    result = IngestionPipeline(session).ingest(request.source, request.record)
    response.status_code = {
        "created": status.HTTP_201_CREATED,
        "quarantined": status.HTTP_202_ACCEPTED,
    }.get(result.status, status.HTTP_200_OK)
    return _result(result)


@router.post("/events/batch", response_model=dict[str, Any])
def ingest_batch(request: BatchEventRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    results = IngestionPipeline(session).ingest_many([(item.source, item.record) for item in request.events])
    return {"results": [_result(result) for result in results]}


def _encode_cursor(timestamp_value: datetime, event_id: str) -> str:
    payload = json.dumps([timestamp_value.isoformat(), event_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        raw_timestamp, event_id = json.loads(decoded)
        timestamp_value = datetime.fromisoformat(raw_timestamp)
        if timestamp_value.tzinfo is None:
            raise ValueError("cursor timestamp is naive")
        return timestamp_value.astimezone(UTC), str(event_id)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid event cursor") from exc


@router.get("/events", response_model=dict[str, Any])
def list_events(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    modality: str | None = None,
    entity_id: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    query = select(Event)
    if modality:
        query = query.where(Event.modality == modality)
    if entity_id:
        query = query.where(Event.entity_id == entity_id)
    if cursor:
        cursor_timestamp, cursor_id = _decode_cursor(cursor)
        query = query.where(or_(Event.timestamp < cursor_timestamp, and_(Event.timestamp == cursor_timestamp, Event.id < cursor_id)))
    rows = list(session.scalars(query.order_by(Event.timestamp.desc(), Event.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1].timestamp.replace(tzinfo=UTC) if page[-1].timestamp.tzinfo is None else page[-1].timestamp, page[-1].id) if len(rows) > limit else None
    return {"items": [event_to_contract(row).model_dump(mode="json") for row in page], "next_cursor": next_cursor}


@router.get("/events/{event_id}", response_model=CanonicalEvent)
def get_event(event_id: str, session: Session = Depends(get_session)) -> CanonicalEvent:
    row = session.get(Event, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    return event_to_contract(row)


@router.get("/quarantine", response_model=dict[str, Any])
def list_quarantine(limit: int = Query(50, ge=1, le=100), session: Session = Depends(get_session)) -> dict[str, Any]:
    rows = list(session.scalars(select(QuarantinedEvent).order_by(QuarantinedEvent.received_at.desc(), QuarantinedEvent.id.desc()).limit(limit)))
    return {"items": [{"id": row.id, "received_at": (row.received_at.replace(tzinfo=UTC) if row.received_at.tzinfo is None else row.received_at).isoformat(), "raw_payload": row.raw_payload, "validation_errors": row.validation_errors} for row in rows]}
