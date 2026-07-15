from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import inspect, text

from app.db.session import engine


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
CATALOGUES = (
    "topology.json",
    "detector_rules.yaml",
    "symptom_families.yaml",
    "hypotheses.yaml",
    "playbooks.yaml",
)


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle) if path.suffix == ".json" else yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain an object")
    if not data.get("schema_version") or not data.get("version"):
        raise ValueError(f"{path.name} is missing schema_version/version")
    return data


def catalogue_status() -> dict[str, str]:
    loaded = {name: _load(FIXTURE_ROOT / name) for name in CATALOGUES}
    topology = loaded["topology.json"]
    node_ids = {node["id"] for node in topology.get("nodes", [])}
    if node_ids != {
        "api-gateway-01",
        "checkout-api-01",
        "payment-api-01",
        "payment-db-01",
        "auth-api-01",
    }:
        raise ValueError("topology does not contain exactly the five frozen entity IDs")
    for edge in topology.get("edges", []):
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            raise ValueError("topology contains a dangling edge")
        if edge["source"] == edge["target"]:
            raise ValueError("topology contains a self-edge")
    return {name: "ready" for name in CATALOGUES}


def database_status() -> str:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    if "alembic_version" not in inspect(engine).get_table_names():
        raise RuntimeError("database migration has not been applied")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if not revision:
        raise RuntimeError("database migration revision is empty")
    return "ready"


def readiness_report() -> tuple[bool, dict[str, Any]]:
    components: dict[str, Any] = {}
    ready = True
    checks = {
        "database": database_status,
        "catalogues": catalogue_status,
        "orchestrator": lambda: __import__(
            "app.orchestration", fromlist=["orchestrator"]
        ).orchestrator.status(),
    }
    for name, check in checks.items():
        try:
            components[name] = check()
        except Exception as exc:  # readiness returns a sanitized component reason
            ready = False
            components[name] = {"status": "error", "reason": str(exc)}
    return ready, components
