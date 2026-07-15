from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypeAlias

import networkx as nx

from app.contracts import TopologyRelation


Direction: TypeAlias = Literal["forward", "reverse"]
NodeState: TypeAlias = Literal[
    "suspected_root", "primary_affected", "impact_path", "blast_radius"
]
EdgeState: TypeAlias = Literal["impact_path", "blast_radius"]
EdgeIdentity: TypeAlias = tuple[str, str, str]

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "topology.json"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})
SUPPORTED_RELATIONS = frozenset(relation.value for relation in TopologyRelation)
SUPPORTED_DIRECTIONS = frozenset({"forward", "reverse"})


class TopologyError(ValueError):
    """Base class for sanitized topology-domain failures."""


class InvalidTopologyError(TopologyError):
    """The checked-in topology fixture is malformed or unsupported."""


class UnknownEntityError(TopologyError):
    """A traversal requested an entity that is not present in the fixture."""


class UnsupportedRelationError(TopologyError):
    """A traversal or fixture used a relation outside the frozen MVP set."""


class UnsupportedDirectionError(TopologyError):
    """A traversal did not explicitly select forward or reverse direction."""


class TopologyPathNotFoundError(TopologyError):
    """No path exists for the requested typed and directed traversal."""


class TopologyGraph:
    """Validated, deterministic typed topology backed by ``nx.MultiDiGraph``."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = deepcopy(dict(payload))
        self._validate_header()
        self.graph = nx.MultiDiGraph()
        self._node_order: dict[str, int] = {}
        self._load_nodes()
        self._load_edges()

    @classmethod
    def from_fixture(cls, path: Path | str = FIXTURE_PATH) -> TopologyGraph:
        fixture_path = Path(path)
        try:
            payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise InvalidTopologyError(f"topology fixture not found: {fixture_path}") from exc
        except json.JSONDecodeError as exc:
            raise InvalidTopologyError("topology fixture is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidTopologyError("topology fixture must contain a JSON object")
        return cls(payload)

    @property
    def fixture_version(self) -> str:
        return str(self._payload["version"])

    @property
    def node_records(self) -> list[dict[str, Any]]:
        return deepcopy(self._payload["nodes"])

    @property
    def edge_records(self) -> list[dict[str, Any]]:
        return deepcopy(self._payload["edges"])

    def get_neighbors(
        self,
        entity_id: str,
        relation_type: TopologyRelation | str,
        direction: Direction | str,
        max_hops: int,
    ) -> list[str]:
        relation = self._relation_value(relation_type)
        checked_direction = self._validate_direction(direction)
        self._validate_entity(entity_id)
        if isinstance(max_hops, bool) or not isinstance(max_hops, int) or max_hops < 1:
            raise TopologyError("max_hops must be a positive integer")

        traversal = self._relation_graph(relation, checked_direction)
        distances = nx.single_source_shortest_path_length(
            traversal, entity_id, cutoff=max_hops
        )
        reachable = ((node, distance) for node, distance in distances.items() if distance > 0)
        return [
            node
            for node, _distance in sorted(
                reachable,
                key=lambda item: (item[1], self._node_order[item[0]]),
            )
        ]

    def get_path(
        self,
        source: str,
        target: str,
        relation_type: TopologyRelation | str,
        direction: Direction | str = "forward",
    ) -> list[str]:
        relation = self._relation_value(relation_type)
        checked_direction = self._validate_direction(direction)
        self._validate_entity(source)
        self._validate_entity(target)
        traversal = self._relation_graph(relation, checked_direction)
        try:
            return list(nx.shortest_path(traversal, source=source, target=target))
        except nx.NetworkXNoPath as exc:
            raise TopologyPathNotFoundError(
                f"no {checked_direction} {relation} path from {source} to {target}"
            ) from exc

    def get_dependency_path(
        self, affected_entity: str, suspected_dependency: str
    ) -> list[str]:
        return self.get_path(
            affected_entity,
            suspected_dependency,
            TopologyRelation.DEPENDS_ON,
            "forward",
        )

    def get_dependency_blast_radius(self, root_entity: str, max_hops: int) -> list[str]:
        return self.get_neighbors(
            root_entity,
            TopologyRelation.DEPENDS_ON,
            "reverse",
            max_hops,
        )

    def get_traffic_impact_path(self, source: str, target: str) -> list[str]:
        return self.get_path(
            source,
            target,
            TopologyRelation.SENDS_TRAFFIC_TO,
            "forward",
        )

    def get_traffic_blast_radius(self, source: str, max_hops: int) -> list[str]:
        return self.get_neighbors(
            source,
            TopologyRelation.SENDS_TRAFFIC_TO,
            "forward",
            max_hops,
        )

    def topology_distance(
        self,
        source: str,
        target: str,
        relation_type: TopologyRelation | str,
        direction: Direction | str,
    ) -> int:
        return len(self.get_path(source, target, relation_type, direction)) - 1

    def snapshot(
        self,
        *,
        node_states: Mapping[str, NodeState] | None = None,
        edge_states: Mapping[EdgeIdentity, EdgeState] | None = None,
    ) -> dict[str, Any]:
        node_states = node_states or {}
        edge_states = edge_states or {}
        unknown_state_nodes = set(node_states).difference(self.graph.nodes)
        if unknown_state_nodes:
            raise UnknownEntityError(
                "topology state references unknown entities: "
                + ", ".join(sorted(unknown_state_nodes))
            )

        nodes = []
        for record in self.node_records:
            nodes.append(
                {
                    "id": record["id"],
                    "name": record["name"],
                    "type": record["entity_type"],
                    "service": record["service"],
                    "criticality": record["criticality"],
                    "state": node_states.get(record["id"]),
                }
            )

        edges = []
        for record in self.edge_records:
            identity = (
                record["source"],
                record["target"],
                record["relation_type"],
            )
            edges.append({**record, "state": edge_states.get(identity)})
        return {"fixture_version": self.fixture_version, "nodes": nodes, "edges": edges}

    def _validate_header(self) -> None:
        schema_version = self._payload.get("schema_version")
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise InvalidTopologyError(
                f"unsupported topology schema_version: {schema_version!r}"
            )
        version = self._payload.get("version")
        if not isinstance(version, str) or not version.strip():
            raise InvalidTopologyError("topology fixture requires a content version")
        if not isinstance(self._payload.get("nodes"), list):
            raise InvalidTopologyError("topology nodes must be a list")
        if not isinstance(self._payload.get("edges"), list):
            raise InvalidTopologyError("topology edges must be a list")

    def _load_nodes(self) -> None:
        required = {"id", "name", "entity_type", "service", "criticality"}
        for index, record in enumerate(self._payload["nodes"]):
            if not isinstance(record, dict) or not required.issubset(record):
                raise InvalidTopologyError(
                    f"topology node at index {index} is missing required fields"
                )
            node_id = record["id"]
            if not isinstance(node_id, str) or not node_id:
                raise InvalidTopologyError(f"topology node at index {index} has an invalid id")
            if node_id in self.graph:
                raise InvalidTopologyError(f"duplicate topology node id: {node_id}")
            self._node_order[node_id] = index
            self.graph.add_node(node_id, **record)
        if not self.graph.nodes:
            raise InvalidTopologyError("topology fixture must contain at least one node")

    def _load_edges(self) -> None:
        required = {"source", "target", "relation_type", "relationship"}
        identities: set[EdgeIdentity] = set()
        for index, record in enumerate(self._payload["edges"]):
            if not isinstance(record, dict) or not required.issubset(record):
                raise InvalidTopologyError(
                    f"topology edge at index {index} is missing required fields"
                )
            source = record["source"]
            target = record["target"]
            relation = record["relation_type"]
            if source not in self.graph or target not in self.graph:
                raise InvalidTopologyError(
                    f"topology edge at index {index} references an unknown entity"
                )
            if source == target:
                raise InvalidTopologyError(f"self-edge is not allowed for entity {source}")
            if relation not in SUPPORTED_RELATIONS:
                raise UnsupportedRelationError(
                    f"unsupported topology relation_type: {relation!r}"
                )
            identity = (source, target, relation)
            if identity in identities:
                raise InvalidTopologyError(
                    f"duplicate typed topology edge: {source} -> {target} ({relation})"
                )
            identities.add(identity)
            self.graph.add_edge(source, target, key=relation, **record)

    def _relation_graph(self, relation: str, direction: Direction) -> nx.DiGraph:
        traversal = nx.DiGraph()
        traversal.add_nodes_from(self.graph.nodes)
        for source, target, _key, data in self.graph.edges(keys=True, data=True):
            if data["relation_type"] != relation:
                continue
            if direction == "forward":
                traversal.add_edge(source, target)
            else:
                traversal.add_edge(target, source)
        return traversal

    def _validate_entity(self, entity_id: str) -> None:
        if entity_id not in self.graph:
            raise UnknownEntityError(f"unknown topology entity: {entity_id}")

    @staticmethod
    def _relation_value(relation_type: TopologyRelation | str) -> str:
        relation = (
            relation_type.value if isinstance(relation_type, TopologyRelation) else relation_type
        )
        if relation not in SUPPORTED_RELATIONS:
            raise UnsupportedRelationError(
                f"unsupported topology relation_type: {relation!r}"
            )
        return relation

    @staticmethod
    def _validate_direction(direction: Direction | str) -> Direction:
        if direction not in SUPPORTED_DIRECTIONS:
            raise UnsupportedDirectionError(
                f"unsupported topology direction: {direction!r}"
            )
        return direction  # type: ignore[return-value]


@lru_cache(maxsize=1)
def get_topology_graph() -> TopologyGraph:
    return TopologyGraph.from_fixture()


def get_neighbors(
    entity_id: str,
    relation_type: TopologyRelation | str,
    direction: Direction | str,
    max_hops: int,
) -> list[str]:
    return get_topology_graph().get_neighbors(
        entity_id, relation_type, direction, max_hops
    )


def get_path(
    source: str,
    target: str,
    relation_type: TopologyRelation | str,
    direction: Direction | str = "forward",
) -> list[str]:
    return get_topology_graph().get_path(source, target, relation_type, direction)


def get_dependency_path(affected_entity: str, suspected_dependency: str) -> list[str]:
    return get_topology_graph().get_dependency_path(
        affected_entity, suspected_dependency
    )


def get_dependency_blast_radius(root_entity: str, max_hops: int) -> list[str]:
    return get_topology_graph().get_dependency_blast_radius(root_entity, max_hops)


def get_traffic_impact_path(source: str, target: str) -> list[str]:
    return get_topology_graph().get_traffic_impact_path(source, target)


def get_traffic_blast_radius(source: str, max_hops: int) -> list[str]:
    return get_topology_graph().get_traffic_blast_radius(source, max_hops)


def topology_distance(
    source: str,
    target: str,
    relation_type: TopologyRelation | str,
    direction: Direction | str,
) -> int:
    return get_topology_graph().topology_distance(
        source, target, relation_type, direction
    )


__all__ = [
    "Direction",
    "InvalidTopologyError",
    "TopologyError",
    "TopologyGraph",
    "TopologyPathNotFoundError",
    "UnknownEntityError",
    "UnsupportedDirectionError",
    "UnsupportedRelationError",
    "get_dependency_blast_radius",
    "get_dependency_path",
    "get_neighbors",
    "get_path",
    "get_topology_graph",
    "get_traffic_blast_radius",
    "get_traffic_impact_path",
    "topology_distance",
]
