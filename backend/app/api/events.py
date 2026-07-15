from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.contracts import (
    AnomalyListResponse,
    BatchIngestionResponse,
    CanonicalEvent,
    EventListResponse,
    IngestionMutationResponse,
    OverviewAnomaly,
    QuarantineListResponse,
    RawIngestionRequest,
)
from app.config import settings
from app.db.repositories import AnomalyRepository, EventRepository
from app.ingestion import ingestion_pipeline
from app.ingestion.pipeline import event_to_contract
from app.orchestration.publisher import OrchestrationPublisher

from .dependencies import get_session
from .error_responses import ERROR_RESPONSES


router = APIRouter(tags=["events"], responses=ERROR_RESPONSES)
DatabaseSession = Annotated[Session, Depends(get_session)]


def _request_id(value: str | None) -> str:
    return value or f"req_{uuid.uuid4().hex}"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _encode_event_cursor(row: Any, filters: dict[str, str | None]) -> str:
    payload = json.dumps(
        {
            "timestamp": _utc(row.timestamp).isoformat(),
            "event_id": row.id,
            "filters": filters,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_event_cursor(
    cursor: str | None,
    filters: dict[str, str | None],
) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if payload.get("filters") != filters:
            raise ValueError("cursor filters changed")
        timestamp = _utc(datetime.fromisoformat(payload["timestamp"]))
        event_id = str(payload["event_id"])
        if not event_id:
            raise ValueError("empty event id")
        return timestamp, event_id
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_CURSOR",
                "message": "Event cursor is malformed or does not match the active filters",
                "details": [],
            },
        ) from exc


@router.post(
    "/events",
    response_model=IngestionMutationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        **ERROR_RESPONSES,
        status.HTTP_200_OK: {"model": IngestionMutationResponse},
        status.HTTP_202_ACCEPTED: {"model": IngestionMutationResponse},
    },
)
def ingest_event(
    request: RawIngestionRequest,
    response: Response,
    session: DatabaseSession,
) -> IngestionMutationResponse:
    result = ingestion_pipeline.ingest(
        source=request.source,
        raw=request.raw,
        request_id=_request_id(request.request_id),
        session=session,
    )
    response.status_code = {
        "accepted": status.HTTP_201_CREATED,
        "collapsed": status.HTTP_200_OK,
        "quarantined": status.HTTP_202_ACCEPTED,
    }[result.status]
    if result.reason_codes == ["IDEMPOTENT_RETRY"]:
        response.status_code = status.HTTP_200_OK
    return result


@router.post("/events/batch", response_model=BatchIngestionResponse)
def ingest_batch(
    requests: list[RawIngestionRequest],
    session: DatabaseSession,
) -> BatchIngestionResponse:
    if len(requests) > settings.event_batch_max_items:
        raise HTTPException(status_code=413, detail={"code": "PAYLOAD_TOO_LARGE"})
    batch_id = f"req_batch_{uuid.uuid4().hex}"
    results: list[IngestionMutationResponse] = []
    accepted_events: list[CanonicalEvent] = []
    for index, request in enumerate(requests):
        result = ingestion_pipeline.ingest(
            source=request.source,
            raw=request.raw,
            request_id=request.request_id or f"{batch_id}:{index}",
            session=session,
            publish=False,
        )
        results.append(result)
        if result.status == "accepted" and not result.reason_codes and result.event_id:
            row = EventRepository(session).get_by_id(result.event_id)
            if row is not None:
                accepted_events.append(event_to_contract(row))

    if accepted_events:
        OrchestrationPublisher(session).publish_batch(accepted_events)
        accepted_ids = {event.event_id for event in accepted_events}
        results = [
            result.model_copy(update={"analysis_state": "processed"})
            if result.event_id in accepted_ids
            else result
            for result in results
        ]
    return BatchIngestionResponse(
        request_id=batch_id,
        generated_at=datetime.now(timezone.utc),
        results=results,
    )

@router.get("/events", response_model=EventListResponse)
def list_events(
    session: DatabaseSession,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    modality: str | None = None,
    entity_id: str | None = None,
) -> EventListResponse:
    filters = {"modality": modality, "entity_id": entity_id}
    cursor_timestamp, cursor_id = _decode_event_cursor(cursor, filters)
    rows = EventRepository(session).list_events(
        limit=limit + 1,
        cursor_timestamp=cursor_timestamp,
        cursor_id=cursor_id,
        modality=modality,
        entity_id=entity_id,
    )
    page = rows[:limit]
    return EventListResponse(
        generated_at=datetime.now(timezone.utc),
        items=[event_to_contract(row) for row in page],
        next_cursor=_encode_event_cursor(page[-1], filters) if len(rows) > limit else None,
    )


@router.get("/events/{event_id}", response_model=CanonicalEvent)
def get_event(event_id: str, session: DatabaseSession) -> CanonicalEvent:
    row = EventRepository(session).get_by_id(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return event_to_contract(row)


@router.get("/anomalies", response_model=AnomalyListResponse)
def list_anomalies(
    session: DatabaseSession,
    limit: int = Query(20, ge=1, le=100),
) -> AnomalyListResponse:
    items: list[OverviewAnomaly] = []
    for row in AnomalyRepository(session).list_recent(limit=limit):
        event = EventRepository(session).get_by_id(row.event_id)
        if event is None:
            continue
        items.append(
            OverviewAnomaly(
                anomaly_id=row.id,
                entity_id=event.entity_id,
                anomaly_type=row.type,
                score=row.score,
                detector_id=row.detector_id,
                detected_at=row.detected_at.replace(
                    tzinfo=row.detected_at.tzinfo or timezone.utc
                ),
            )
        )
    return AnomalyListResponse(
        generated_at=datetime.now(timezone.utc),
        items=items,
    )


@router.get("/quarantine", response_model=QuarantineListResponse)
def list_quarantine(session: DatabaseSession) -> QuarantineListResponse:
    rows = EventRepository(session).list_quarantined()
    return QuarantineListResponse(
        generated_at=datetime.now(timezone.utc),
        items=[
            {
                "quarantine_id": row.id,
                "received_at": row.received_at.replace(
                    tzinfo=row.received_at.tzinfo or timezone.utc
                ),
                "validation_errors": row.validation_errors,
                "raw_payload": row.raw_payload,
            }
            for row in rows
        ],
    )
