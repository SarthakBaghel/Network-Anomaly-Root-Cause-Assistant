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
SUPPORTED_CATALOGUE_VERSIONS = {
    "topology.json": ("1.0", "topology-1.2"),
    "detector_rules.yaml": ("1.0", "detector-rules-1.2"),
    "symptom_families.yaml": ("1.0", "symptom-families-1.2"),
    "hypotheses.yaml": ("1.0", "hypotheses-1.4"),
    "playbooks.yaml": ("1.0", "playbooks-1.3"),
}


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle) if path.suffix == ".json" else yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain an object")
    if not data.get("schema_version") or not data.get("version"):
        raise ValueError(f"{path.name} is missing schema_version/version")
    supported = SUPPORTED_CATALOGUE_VERSIONS.get(path.name)
    if supported is not None and (data["schema_version"], data["version"]) != supported:
        raise ValueError(
            f"{path.name} has unsupported schema/version {data['schema_version']}/{data['version']}"
        )
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
        "hdfs-client-01",
        "namenode-01",
        "datanode-01",
    }:
        raise ValueError("topology does not contain exactly the declared entity IDs")
    for edge in topology.get("edges", []):
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            raise ValueError("topology contains a dangling edge")
        if edge["source"] == edge["target"]:
            raise ValueError("topology contains a self-edge")
    hypotheses = loaded["hypotheses.yaml"].get("hypotheses", [])
    playbook_steps = loaded["playbooks.yaml"].get("steps", [])
    hypothesis_types = [row.get("hypothesis_type") for row in hypotheses]
    if len(hypothesis_types) != len(set(hypothesis_types)):
        raise ValueError("hypothesis types must be unique")
    step_by_id = {row.get("step_id"): row for row in playbook_steps}
    if len(step_by_id) != len(playbook_steps) or None in step_by_id:
        raise ValueError("playbook step IDs must be present and unique")
    for hypothesis in hypotheses:
        hypothesis_type = hypothesis.get("hypothesis_type")
        entity_types = set(hypothesis.get("entity_types", []))
        diagnostic_ids = hypothesis.get("diagnostic_step_ids") or []
        remediation_ids = hypothesis.get("remediation_step_ids") or []
        declared = [*diagnostic_ids, *remediation_ids]
        if len(declared) != len(set(declared)):
            raise ValueError(f"hypothesis {hypothesis_type!r} repeats a playbook step ID")
        for step_id in declared:
            step = step_by_id.get(step_id)
            if step is None:
                raise ValueError(
                    f"hypothesis {hypothesis_type!r} references unknown step {step_id!r}"
                )
            if hypothesis_type not in step.get("applicable_hypothesis_types", []):
                raise ValueError(
                    f"step {step_id!r} is incompatible with hypothesis {hypothesis_type!r}"
                )
            if not entity_types.intersection(step.get("applicable_entity_types", [])):
                raise ValueError(f"step {step_id!r} has no compatible hypothesis entity type")
            expected_type = "diagnostic" if step_id in diagnostic_ids else "remediation"
            if step.get("step_type") != expected_type:
                raise ValueError(
                    f"step {step_id!r} is declared as {expected_type} but catalogue type is "
                    f"{step.get('step_type')!r}"
                )
    return {name: "ready" for name in CATALOGUES}


def database_status() -> str:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    if "alembic_version" not in inspect(engine).get_table_names():
        raise RuntimeError("database migration has not been applied")
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
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
