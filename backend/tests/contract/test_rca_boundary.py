from __future__ import annotations

import ast
from pathlib import Path

from pydantic import ValidationError
import pytest

from app.rca import (
    HypothesisCandidate,
    RankedHypothesis,
    RcaComputationResult,
)
from app.contracts import EvidenceCoverage


ROOT = Path(__file__).resolve().parents[3]


def test_pure_rca_contract_has_no_database_or_orchestration_imports() -> None:
    path = ROOT / "backend" / "app" / "rca" / "contracts.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not any(name.startswith("sqlalchemy") for name in imports)
    assert not any(name.startswith("app.db") for name in imports)
    assert not any(name.startswith("app.orchestration") for name in imports)


def test_computation_result_is_immutable_and_byte_stable() -> None:
    candidate = HypothesisCandidate(
        candidate_id="candidate-1",
        hypothesis_type="configuration_regression",
        candidate_entity_id="api-gateway-01",
    )
    ranked = RankedHypothesis(
        hypothesis_id="hypothesis-1",
        candidate_id=candidate.candidate_id,
        hypothesis_type=candidate.hypothesis_type,
        candidate_entity_id=candidate.candidate_entity_id,
        rank=1,
        evidence_score=92.1,
        evidence_coverage=EvidenceCoverage(available=6, expected=7),
        factor_scores={"symptom_compatibility": 1.0},
        summary="A probable configuration regression.",
    )
    first = RcaComputationResult(candidates=(candidate,), ranked_hypotheses=(ranked,))
    second = RcaComputationResult.model_validate(first.model_dump(mode="json"))

    assert first.canonical_json() == second.canonical_json()
    with pytest.raises(ValidationError):
        first.candidates = ()


def test_ranked_hypothesis_must_reference_candidate_and_consecutive_rank() -> None:
    candidate = HypothesisCandidate(
        candidate_id="candidate-1",
        hypothesis_type="configuration_regression",
        candidate_entity_id="api-gateway-01",
    )
    with pytest.raises(ValidationError, match="unique and consecutive"):
        RcaComputationResult(
            candidates=(candidate,),
            ranked_hypotheses=(
                RankedHypothesis(
                    hypothesis_id="hypothesis-1",
                    candidate_id="candidate-1",
                    hypothesis_type="configuration_regression",
                    candidate_entity_id="api-gateway-01",
                    rank=2,
                    evidence_score=92.1,
                    evidence_coverage=EvidenceCoverage(available=0, expected=0),
                    factor_scores={},
                    summary="Invalid rank.",
                ),
            ),
        )
