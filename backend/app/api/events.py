from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.contracts import (
    BatchIngestionResponse,
    CanonicalEvent,
    IngestionMutationResponse,
    RawIngestionRequest,
)
from app.config import settings
from app.db import models
from app.db.repositories import EventRepository
from app.ingestion import ingestion_pipeline

from .dependencies import get_session


router = APIRouter(tags=["events"])
DatabaseSession = Annotated[Session, Depends(get_session)]


def _request_id(value: str | None) -> str:
    return value or f"req_{uuid.uuid4().hex}"


def _event_contract(row: models.Event) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=row.id,
        timestamp=row.timestamp.replace(tzinfo=row.timestamp.tzinfo or timezone.utc),
        ingested_at=row.ingested_at.replace(tzinfo=row.ingested_at.tzinfo or timezone.utc),
        entity_id=row.entity_id,
        modality=row.modality,
        event_type=row.event_type,
        severity=row.severity,
        signal_name=row.signal_name,
        signal_value=row.signal_value,
        unit=row.unit,
        trace_or_session_id=row.trace_or_session_id,
        source=row.source,
        source_record_id=row.source_record_id,
        schema_version=row.schema_version,
        quality_flags=list(row.quality_flags or []),
        raw_payload=dict(row.raw_payload or {}),
    )


@router.post("/events", response_model=IngestionMutationResponse)
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
    results = [
        ingestion_pipeline.ingest(
            source=request.source,
            raw=request.raw,
            request_id=request.request_id or f"{batch_id}:{index}",
            session=session,
        )
        for index, request in enumerate(requests)
    ]
    return BatchIngestionResponse(
        request_id=batch_id,
        generated_at=datetime.now(timezone.utc),
        results=results,
    )


@router.get("/events", response_model=list[CanonicalEvent])
def list_events(
    session: DatabaseSession,
    limit: int = Query(50, ge=1, le=200),
    modality: str | None = None,
    entity_id: str | None = None,
) -> list[CanonicalEvent]:
    return [
        _event_contract(row)
        for row in EventRepository(session).list_events(
            limit=limit, modality=modality, entity_id=entity_id
        )
    ]


@router.get("/events/{event_id}", response_model=CanonicalEvent)
def get_event(event_id: str, session: DatabaseSession) -> CanonicalEvent:
    row = EventRepository(session).get_by_id(event_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
    return _event_contract(row)


@router.get("/quarantine", response_model=dict[str, Any])
def list_quarantine(session: DatabaseSession) -> dict[str, Any]:
    rows = EventRepository(session).list_quarantined()
    return {
        "generated_at": datetime.now(timezone.utc),
        "items": [
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
    }
