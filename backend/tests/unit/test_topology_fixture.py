import json
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOPOLOGY = ROOT / "backend" / "app" / "fixtures" / "topology.json"


def path(source: str, target: str, relation: str) -> list[str]:
    payload = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    adjacency: dict[str, list[str]] = {}
    for edge in payload["edges"]:
        if edge["relation_type"] == relation:
            adjacency.setdefault(edge["source"], []).append(edge["target"])
    queue = deque([(source, [source])])
    while queue:
        current, current_path = queue.popleft()
        if current == target:
            return current_path
        for neighbor in adjacency.get(current, []):
            if neighbor not in current_path:
                queue.append((neighbor, [*current_path, neighbor]))
    return []


def test_frozen_traffic_path_is_three_hops_to_database() -> None:
    assert path("api-gateway-01", "payment-db-01", "sends_traffic_to") == [
        "api-gateway-01",
        "checkout-api-01",
        "payment-api-01",
        "payment-db-01",
    ]


def test_all_edge_endpoints_exist() -> None:
    payload = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    nodes = {item["id"] for item in payload["nodes"]}
    assert nodes == {
        "api-gateway-01",
        "checkout-api-01",
        "payment-api-01",
        "payment-db-01",
        "auth-api-01",
    }
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in payload["edges"])

