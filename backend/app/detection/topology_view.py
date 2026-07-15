"""
TopologyView — Lightweight in-memory view of the topology graph for cascade detection.

Built from the topology_edges DB table at detection time. Provides the
`distance(from_entity, to_entity, relation_type)` method that the
TopologyCascadeDetector expects.

Design decisions:
  - Rebuilt on each call to _build_for_session() from the DB (single query)
  - Not cached between events — topology rarely changes and the query is fast
  - Only traverses edges of the requested relation_type, not all edges
  - BFS up to INCIDENT_MAX_TOPOLOGY_HOPS (2) — prevents runaway traversal
  - Returns None if no path found within the hop limit

BLUEPRINT §12.2: traversal is strictly typed (sends_traffic_to / depends_on).
BLUEPRINT §13.1: hop limit = 2 per INCIDENT_MAX_TOPOLOGY_HOPS.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

MAX_HOPS = 2


class TopologyView:
    """BFS-based typed topology graph for cascade distance queries."""

    def __init__(self, edges: list[tuple[str, str, str]]) -> None:
        # edges: list of (source_entity_id, target_entity_id, relation_type)
        self._adj: dict[tuple[str, str], list[str]] = {}
        for src, tgt, rel in edges:
            self._adj.setdefault((src, rel), []).append(tgt)

    def distance(self, from_entity: str, to_entity: str, relation_type: str) -> int | None:
        """Return the BFS hop distance from from_entity to to_entity via relation_type.

        Returns None if no path exists within MAX_HOPS.
        BLUEPRINT §13.1: hop limit is fixed at INCIDENT_MAX_TOPOLOGY_HOPS = 2.
        """
        if from_entity == to_entity:
            return 0
        visited: set[str] = {from_entity}
        queue: deque[tuple[str, int]] = deque([(from_entity, 0)])
        while queue:
            current, hops = queue.popleft()
            if hops >= MAX_HOPS:
                continue
            for neighbour in self._adj.get((current, relation_type), []):
                if neighbour == to_entity:
                    return hops + 1
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append((neighbour, hops + 1))
        return None

    @classmethod
    def build_for_session(cls, session: Session) -> "TopologyView":
        """Build a TopologyView from the current topology_edges rows in DB."""
        from app.db.models import TopologyEdge
        from sqlalchemy import select

        rows = session.scalars(select(TopologyEdge)).all()
        edges = [(row.source_entity_id, row.target_entity_id, row.relation_type) for row in rows]
        return cls(edges)
