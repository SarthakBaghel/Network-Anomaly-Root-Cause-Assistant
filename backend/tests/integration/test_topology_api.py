from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api.topology as topology_api
from app.main import app


client = TestClient(app)


def test_full_topology_returns_typed_fixture_without_incident_state() -> None:
    response = client.get("/api/v1/topology")
    assert response.status_code == 200
    payload = response.json()
    assert payload["fixture_version"] == "topology-1.2"
    assert len(payload["nodes"]) == 8
    assert len(payload["edges"]) == 12
    assert {edge["relation_type"] for edge in payload["edges"]} == {
        "depends_on",
        "sends_traffic_to",
    }
    assert all(node["state"] is None for node in payload["nodes"])
    assert all(edge["state"] is None for edge in payload["edges"])


def test_incident_topology_annotates_root_affected_nodes_and_impact_edges(
    monkeypatch,
) -> None:
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get(self, model, object_id):
            if model is topology_api.Incident and object_id == "inc_test":
                return SimpleNamespace(
                    top_hypothesis_id="hyp_test",
                    affected_entity_ids=[
                        "api-gateway-01",
                        "checkout-api-01",
                        "payment-api-01",
                    ],
                    primary_entity_id="api-gateway-01",
                )
            if model is topology_api.Hypothesis and object_id == "hyp_test":
                return SimpleNamespace(candidate_entity_id="api-gateway-01")
            return None

    monkeypatch.setattr(topology_api, "SessionLocal", FakeSession)
    response = client.get("/api/v1/topology", params={"incident_id": "inc_test"})
    assert response.status_code == 200
    payload = response.json()
    node_states = {node["id"]: node["state"] for node in payload["nodes"]}
    assert node_states["api-gateway-01"] == "suspected_root"
    assert node_states["checkout-api-01"] == "impact_path"
    assert node_states["payment-api-01"] == "impact_path"
    impact_edges = {
        (edge["source"], edge["target"], edge["relation_type"])
        for edge in payload["edges"]
        if edge["state"] == "impact_path"
    }
    assert impact_edges == {
        ("api-gateway-01", "checkout-api-01", "sends_traffic_to"),
        ("checkout-api-01", "payment-api-01", "sends_traffic_to"),
    }


def test_typed_path_endpoint_returns_distance_and_entity_sequence() -> None:
    response = client.get(
        "/api/v1/topology/path",
        params={
            "source": "api-gateway-01",
            "target": "payment-db-01",
            "relation_type": "sends_traffic_to",
            "direction": "forward",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "source": "api-gateway-01",
        "target": "payment-db-01",
        "relation_type": "sends_traffic_to",
        "direction": "forward",
        "distance": 3,
        "entity_ids": [
            "api-gateway-01",
            "checkout-api-01",
            "payment-api-01",
            "payment-db-01",
        ],
    }


def test_blast_radius_modes_apply_frozen_relation_and_direction() -> None:
    dependency = client.get(
        "/api/v1/topology/blast-radius/payment-db-01",
        params={"mode": "dependency", "max_hops": 3},
    )
    assert dependency.status_code == 200
    assert dependency.json()["relation_type"] == "depends_on"
    assert dependency.json()["direction"] == "reverse"
    assert dependency.json()["entity_ids"] == [
        "payment-api-01",
        "checkout-api-01",
        "api-gateway-01",
    ]

    traffic = client.get(
        "/api/v1/topology/blast-radius/api-gateway-01",
        params={"mode": "traffic", "max_hops": 3},
    )
    assert traffic.status_code == 200
    assert traffic.json()["relation_type"] == "sends_traffic_to"
    assert traffic.json()["direction"] == "forward"
    assert set(traffic.json()["entity_ids"]) == {
        "checkout-api-01",
        "payment-api-01",
        "payment-db-01",
        "auth-api-01",
    }


def test_topology_query_validation_and_not_found_errors() -> None:
    missing_relation = client.get(
        "/api/v1/topology/path",
        params={
            "source": "api-gateway-01",
            "target": "payment-db-01",
            "direction": "forward",
        },
    )
    assert missing_relation.status_code == 422

    invalid_mode = client.get(
        "/api/v1/topology/blast-radius/api-gateway-01",
        params={"mode": "connected"},
    )
    assert invalid_mode.status_code == 422

    unknown_entity = client.get(
        "/api/v1/topology/blast-radius/missing-entity",
        params={"mode": "traffic"},
    )
    assert unknown_entity.status_code == 404
    assert unknown_entity.json()["error"]["code"] == "TOPOLOGY_NOT_FOUND"

    missing_incident = client.get("/api/v1/topology", params={"incident_id": "missing-incident"})
    assert missing_incident.status_code == 404
    assert missing_incident.json()["error"]["code"] == "INCIDENT_NOT_FOUND"
