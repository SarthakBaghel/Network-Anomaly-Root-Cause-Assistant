from __future__ import annotations

import json
from pathlib import Path

from app.orchestration.orchestrator import ALGORITHM_VERSION
from app.rca import AnalysisEngine, WEIGHT_VALUES
from tests.support.rca_prerequisites import build_golden_analysis_bundle


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "golden_expected_analysis.json"


def _fixture_projection():
    bundle = build_golden_analysis_bundle()
    result = AnalysisEngine().analyse(bundle)
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "analysis_run_id": "run_007",
        "conflict_reason_codes": list(result.conflict_reason_codes),
        "hypotheses": [
            {
                "analysis_run_id": "run_007",
                "candidate_entity_id": item.candidate_entity_id,
                "evidence_coverage": item.evidence_coverage.model_dump(mode="json"),
                "evidence_score": item.evidence_score,
                "factor_scores": item.factor_scores,
                "hypothesis_id": item.hypothesis_id,
                "hypothesis_type": item.hypothesis_type,
                "incident_id": bundle.incident.incident_id,
                "rank": item.rank,
                "summary": item.summary,
            }
            for item in result.ranked_hypotheses
        ],
        "incident_id": bundle.incident.incident_id,
        "schema_version": "1.0",
        "typed_paths": {
            key: list(path) for key, path in result.typed_paths.items()
        },
        "version": "golden-expected-analysis-1.0",
        "weights": WEIGHT_VALUES,
    }


def test_engine_reproduces_frozen_expected_analysis_exactly() -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert _fixture_projection() == expected
