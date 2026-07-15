from __future__ import annotations

from itertools import pairwise
from typing import Annotated, Any, Literal, Never

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.contracts import TopologyRelation, TopologySnapshot
from app.db.models import Hypothesis, Incident
from app.db.session import SessionLocal, get_session
from app.topology.graph import (
    EdgeIdentity,
    EdgeState,
    NodeState,
    TopologyError,
    TopologyGraph,
    TopologyPathNotFoundError,
    UnknownEntityError,
    get_topology_graph,
)


Direction = Literal["forward", "reverse"]
BlastRadiusMode = Literal["dependency", "traffic"]

router = APIRouter(prefix="/topology", tags=["topology"])


def _raise_api_error(exc: TopologyError) -> Never:
    if isinstance(exc, (UnknownEntityError, TopologyPathNotFoundError)):
        status_code = status.HTTP_404_NOT_FOUND
        code = "TOPOLOGY_NOT_FOUND"
    else:
        status_code = status.HTTP_400_BAD_REQUEST
        code = "INVALID_TOPOLOGY_REQUEST"
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(exc), "details": []},
    ) from exc


def _incident_annotation(
    graph: TopologyGraph,
    incident_id: str,
    session: Session | None = None,
    analysis_run_id: str | None = None,
) -> tuple[dict[str, NodeState], dict[EdgeIdentity, EdgeState]]:
    if session is None:
        with SessionLocal() as s:
            return _incident_annotation_impl(
                graph,
                incident_id,
                s,
                analysis_run_id=analysis_run_id,
            )
    else:
        return _incident_annotation_impl(
            graph,
            incident_id,
            session,
            analysis_run_id=analysis_run_id,
        )


def _incident_annotation_impl(
    graph: TopologyGraph,
    incident_id: str,
    session: Session,
    *,
    analysis_run_id: str | None = None,
) -> tuple[dict[str, NodeState], dict[EdgeIdentity, EdgeState]]:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "INCIDENT_NOT_FOUND",
                "message": f"incident not found: {incident_id}",
                "details": [],
            },
        )
    if analysis_run_id is not None:
        top_hypothesis = session.scalar(
            select(Hypothesis)
            .where(Hypothesis.analysis_run_id == analysis_run_id)
            .order_by(Hypothesis.rank.asc())
        )
    else:
        top_hypothesis = (
            session.get(Hypothesis, incident.top_hypothesis_id)
            if incident.top_hypothesis_id
            else None
        )
    affected_entity_ids = list(incident.affected_entity_ids)
    primary_entity_id = incident.primary_entity_id

    suspected_root = (
        top_hypothesis.candidate_entity_id if top_hypothesis is not None else primary_entity_id
    )
    node_states: dict[str, NodeState] = {
        entity_id: "impact_path" for entity_id in affected_entity_ids
    }
    node_states[primary_entity_id] = "primary_affected"
    node_states[suspected_root] = "suspected_root"

    edge_states: dict[EdgeIdentity, EdgeState] = {}
    for affected_entity_id in affected_entity_ids:
        if affected_entity_id == suspected_root:
            continue
        try:
            path = graph.get_traffic_impact_path(suspected_root, affected_entity_id)
        except TopologyPathNotFoundError:
            continue
        for source, target in pairwise(path):
            edge_states[(source, target, TopologyRelation.SENDS_TRAFFIC_TO.value)] = (
                "impact_path"
            )
    return node_states, edge_states


@router.get("", response_model=TopologySnapshot)
def topology(
    incident_id: Annotated[str | None, Query(min_length=1)] = None,
) -> TopologySnapshot:
    graph = get_topology_graph()
    node_states: dict[str, NodeState] = {}
    edge_states: dict[EdgeIdentity, EdgeState] = {}
    if incident_id is not None:
        node_states, edge_states = _incident_annotation(graph, incident_id)
    try:
        return TopologySnapshot.model_validate(
            graph.snapshot(node_states=node_states, edge_states=edge_states)
        )
    except TopologyError as exc:
        _raise_api_error(exc)


@router.get("/path", response_model=dict[str, Any])
def path(
    source: Annotated[str, Query(min_length=1)],
    target: Annotated[str, Query(min_length=1)],
    relation_type: TopologyRelation,
    direction: Direction,
) -> dict[str, Any]:
    try:
        entity_ids = get_topology_graph().get_path(
            source, target, relation_type, direction
        )
    except TopologyError as exc:
        _raise_api_error(exc)
    return {
        "source": source,
        "target": target,
        "relation_type": relation_type.value,
        "direction": direction,
        "distance": len(entity_ids) - 1,
        "entity_ids": entity_ids,
    }


@router.get("/blast-radius/{entity_id}", response_model=dict[str, Any])
def blast_radius(
    entity_id: str,
    mode: BlastRadiusMode,
    max_hops: Annotated[int, Query(ge=1, le=20)] = settings.incident_max_topology_hops,
) -> dict[str, Any]:
    graph = get_topology_graph()
    try:
        if mode == "dependency":
            relation_type = TopologyRelation.DEPENDS_ON
            direction: Direction = "reverse"
            entity_ids = graph.get_dependency_blast_radius(entity_id, max_hops)
        else:
            relation_type = TopologyRelation.SENDS_TRAFFIC_TO
            direction = "forward"
            entity_ids = graph.get_traffic_blast_radius(entity_id, max_hops)
    except TopologyError as exc:
        _raise_api_error(exc)
    return {
        "root_entity_id": entity_id,
        "mode": mode,
        "relation_type": relation_type.value,
        "direction": direction,
        "max_hops": max_hops,
        "entity_ids": entity_ids,
    }
