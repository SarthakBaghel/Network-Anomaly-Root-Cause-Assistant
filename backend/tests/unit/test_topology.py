from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import networkx as nx
import pytest

from app.topology.graph import (
    InvalidTopologyError,
    TopologyGraph,
    TopologyPathNotFoundError,
    UnknownEntityError,
    UnsupportedDirectionError,
    UnsupportedRelationError,
)


ROOT = Path(__file__).resolve().parents[3]
TOPOLOGY_FIXTURE = ROOT / "backend" / "app" / "fixtures" / "topology.json"


@pytest.fixture
def payload() -> dict:
    return json.loads(TOPOLOGY_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def graph(payload: dict) -> TopologyGraph:
    return TopologyGraph(payload)


def test_fixture_loads_as_multidigraph_with_parallel_typed_edges(
    graph: TopologyGraph,
) -> None:
    assert isinstance(graph.graph, nx.MultiDiGraph)
    assert graph.fixture_version == "topology-1.1"
    assert graph.graph.number_of_nodes() == 5
    assert graph.graph.number_of_edges("api-gateway-01", "checkout-api-01") == 2


def test_generic_dependency_search_is_forward_from_affected_service(
    graph: TopologyGraph,
) -> None:
    assert graph.get_neighbors(
        "api-gateway-01", "depends_on", "forward", max_hops=2
    ) == [
        "checkout-api-01",
        "auth-api-01",
        "payment-api-01",
    ]


def test_dependency_blast_radius_is_reverse_from_failed_dependency(
    graph: TopologyGraph,
) -> None:
    assert graph.get_dependency_blast_radius("payment-db-01", max_hops=3) == [
        "payment-api-01",
        "checkout-api-01",
        "api-gateway-01",
    ]


def test_traffic_blast_radius_follows_downstream_traffic(graph: TopologyGraph) -> None:
    assert graph.get_traffic_blast_radius("api-gateway-01", max_hops=2) == [
        "checkout-api-01",
        "auth-api-01",
        "payment-api-01",
    ]
    assert graph.get_traffic_blast_radius("api-gateway-01", max_hops=3) == [
        "checkout-api-01",
        "auth-api-01",
        "payment-api-01",
        "payment-db-01",
    ]


def test_dependency_and_traffic_paths_use_only_the_requested_relation(
    graph: TopologyGraph,
) -> None:
    assert graph.get_dependency_path("checkout-api-01", "payment-db-01") == [
        "checkout-api-01",
        "payment-api-01",
        "payment-db-01",
    ]
    assert graph.get_traffic_impact_path("api-gateway-01", "payment-db-01") == [
        "api-gateway-01",
        "checkout-api-01",
        "payment-api-01",
        "payment-db-01",
    ]


def test_topology_distance_counts_edges_and_honors_direction(
    graph: TopologyGraph,
) -> None:
    assert (
        graph.topology_distance(
            "api-gateway-01",
            "payment-db-01",
            "sends_traffic_to",
            "forward",
        )
        == 3
    )
    assert (
        graph.topology_distance(
            "payment-db-01",
            "api-gateway-01",
            "sends_traffic_to",
            "reverse",
        )
        == 3
    )


def test_unknown_entities_and_missing_typed_paths_raise_domain_errors(
    graph: TopologyGraph,
) -> None:
    with pytest.raises(UnknownEntityError, match="unknown topology entity"):
        graph.get_neighbors("missing-entity", "depends_on", "forward", max_hops=1)
    with pytest.raises(TopologyPathNotFoundError, match="no forward depends_on path"):
        graph.get_dependency_path("auth-api-01", "payment-db-01")


def test_self_edges_are_rejected(payload: dict) -> None:
    invalid = deepcopy(payload)
    invalid["edges"].append(
        {
            "source": "api-gateway-01",
            "target": "api-gateway-01",
            "relation_type": "depends_on",
            "relationship": "invalid_self_reference",
        }
    )
    with pytest.raises(InvalidTopologyError, match="self-edge"):
        TopologyGraph(invalid)


def test_unsupported_relation_types_are_rejected_in_fixtures_and_queries(
    payload: dict,
    graph: TopologyGraph,
) -> None:
    invalid = deepcopy(payload)
    invalid["edges"][0]["relation_type"] = "connected_to"
    with pytest.raises(UnsupportedRelationError, match="unsupported topology relation_type"):
        TopologyGraph(invalid)
    with pytest.raises(UnsupportedRelationError, match="unsupported topology relation_type"):
        graph.get_neighbors("api-gateway-01", "connected_to", "forward", max_hops=1)


def test_direction_and_hop_limit_must_be_explicit_and_valid(graph: TopologyGraph) -> None:
    with pytest.raises(UnsupportedDirectionError, match="unsupported topology direction"):
        graph.get_neighbors("api-gateway-01", "depends_on", "both", max_hops=1)
    with pytest.raises(ValueError, match="max_hops must be a positive integer"):
        graph.get_neighbors("api-gateway-01", "depends_on", "forward", max_hops=0)


def test_snapshot_maps_fixture_entity_type_to_api_type(graph: TopologyGraph) -> None:
    snapshot = graph.snapshot(
        node_states={"api-gateway-01": "suspected_root"},
        edge_states={
            ("api-gateway-01", "checkout-api-01", "sends_traffic_to"): "impact_path"
        },
    )
    gateway = next(node for node in snapshot["nodes"] if node["id"] == "api-gateway-01")
    traffic_edge = next(
        edge
        for edge in snapshot["edges"]
        if edge["source"] == "api-gateway-01"
        and edge["target"] == "checkout-api-01"
        and edge["relation_type"] == "sends_traffic_to"
    )
    assert gateway["type"] == "gateway"
    assert gateway["state"] == "suspected_root"
    assert traffic_edge["state"] == "impact_path"

