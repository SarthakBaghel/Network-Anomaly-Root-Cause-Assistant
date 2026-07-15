from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.contracts import (  # noqa: E402
    AnalysisRun,
    AnomalyRecord,
    AuditRecord,
    CanonicalEvent,
    ErrorEnvelope,
    EvidenceItem,
    Hypothesis,
    IncidentSummary,
    InvestigationResponse,
    ReviewMutationResponse,
    ReviewRecord,
    ReviewRequest,
)
from app.readiness import catalogue_status  # noqa: E402


HANDOFFS = (
    "backend/openapi.json",
    "backend/app/fixtures/topology.json",
    "backend/app/fixtures/hypotheses.yaml",
    "backend/app/fixtures/symptom_families.yaml",
    "backend/tests/fixtures/golden_events.jsonl",
    "backend/tests/fixtures/golden_anomalies.json",
    "backend/tests/fixtures/golden_incident_bundle.json",
    "backend/tests/fixtures/golden_expected_analysis.json",
    "backend/tests/fixtures/golden_investigation_response.json",
    "backend/tests/fixtures/golden_review_examples.json",
    "backend/tests/fixtures/golden_audit_examples.json",
    "frontend/src/routes.ts",
    "frontend/src/test-fixtures/testid-manifest.ts",
)


def load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def validate_python() -> None:
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12+ is required")


def validate_node(require_node22: bool) -> None:
    result = subprocess.run(["node", "--version"], check=True, capture_output=True, text=True)
    major = int(result.stdout.strip().removeprefix("v").split(".", 1)[0])
    if require_node22 and major != 22:
        raise RuntimeError(f"Node 22 LTS is required; active runtime is {result.stdout.strip()}")


def validate_contracts() -> None:
    examples = ROOT / "backend" / "app" / "contracts" / "examples"
    example_models = {
        "canonical_event.json": CanonicalEvent,
        "anomaly.json": AnomalyRecord,
        "incident.json": IncidentSummary,
        "hypothesis.json": Hypothesis,
        "evidence.json": EvidenceItem,
        "review.json": ReviewRecord,
        "review-request.json": ReviewRequest,
        "review-mutation-response.json": ReviewMutationResponse,
        "analysis_run.json": AnalysisRun,
        "error.json": ErrorEnvelope,
    }
    for name, model in example_models.items():
        model.model_validate_json((examples / name).read_text(encoding="utf-8"))

    events = [
        CanonicalEvent.model_validate_json(line)
        for line in (ROOT / "backend/tests/fixtures/golden_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    if len(events) < 20:
        raise ValueError("golden event fixture does not contain enough baseline records")
    anomalies = load("backend/tests/fixtures/golden_anomalies.json")
    for item in [*anomalies["anomalies"], *anomalies["context_markers"]]:
        AnomalyRecord.model_validate(item)
    if len(anomalies["anomalies"]) != 9 or len(anomalies["context_markers"]) != 1:
        raise ValueError("golden anomaly/context-marker split is not frozen as 9 + 1")

    analysis = load("backend/tests/fixtures/golden_expected_analysis.json")
    hypotheses = [Hypothesis.model_validate(item) for item in analysis["hypotheses"]]
    if [item.evidence_score for item in hypotheses] != [92.1, 65.6, 41.5]:
        raise ValueError("frozen evidence scores changed")
    IncidentSummary.model_validate(load("backend/tests/fixtures/golden_incident_bundle.json")["incident"])
    response = InvestigationResponse.model_validate(
        load("backend/tests/fixtures/golden_investigation_response.json")
    )
    response.assert_consistent_run()
    for item in load("backend/tests/fixtures/golden_review_examples.json")["records"]:
        ReviewRecord.model_validate(item)
    for item in load("backend/tests/fixtures/golden_audit_examples.json")["records"]:
        AuditRecord.model_validate(item)


def validate_runtime_firewall() -> None:
    packages = ("ingestion", "detection", "incidents", "topology", "rca", "evidence", "playbooks", "explanation")
    forbidden = ("ground_truth", "golden_expected", "golden_anomalies", "/expected/")
    violations = []
    for package in packages:
        for path in (BACKEND / "app" / package).rglob("*.py"):
            content = path.read_text(encoding="utf-8").lower()
            if any(token in content for token in forbidden):
                violations.append(str(path.relative_to(ROOT)))
    if violations:
        raise ValueError("runtime ground-truth firewall violations: " + ", ".join(violations))


def validate_generators() -> None:
    subprocess.run([sys.executable, "scripts/build_scenario_bundle.py", "--check"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/build_handoff_fixtures.py", "--check"], cwd=ROOT, check=True)


def validate_frontend_manifest() -> None:
    text = (ROOT / "frontend/src/test-fixtures/testid-manifest.ts").read_text(encoding="utf-8")
    values = re.findall(r"'([a-z][a-z0-9-]+)'", text)
    if len(values) != len(set(values)):
        raise ValueError("frontend data-testid manifest contains duplicates")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest() -> None:
    manifest = ROOT / "docs" / "handoff-manifest.md"
    text = manifest.read_text(encoding="utf-8")
    heading = "## Generated checksums"
    prefix = text.split(heading, 1)[0].rstrip()
    rows = ["| Artifact | SHA-256 |", "|---|---|"]
    for relative in HANDOFFS:
        path = ROOT / relative
        rows.append(f"| `{relative}` | `{sha256(path)}` |")
    manifest.write_text(f"{prefix}\n\n{heading}\n\n" + "\n".join(rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--allow-node-mismatch", action="store_true")
    args = parser.parse_args()
    validate_python()
    validate_node(require_node22=not args.allow_node_mismatch)
    catalogue_status()
    validate_generators()
    validate_contracts()
    validate_runtime_firewall()
    validate_frontend_manifest()
    missing = [relative for relative in HANDOFFS if not (ROOT / relative).exists()]
    if missing:
        raise ValueError("missing handoffs: " + ", ".join(missing))
    if args.write_manifest:
        write_manifest()
    print("Milestone-0 contracts and handoffs are valid")


if __name__ == "__main__":
    main()
