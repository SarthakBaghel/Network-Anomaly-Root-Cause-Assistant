from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "golden_expected_analysis.json"


def calculate(factors: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(Decimal(str(weights[name])) * Decimal(str(value)) for name, value in factors.items())
    return float((Decimal("100") * total).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def test_frozen_scores_are_derived_from_factors() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    scores = [calculate(item["factor_scores"], payload["weights"]) for item in payload["hypotheses"]]
    assert scores == [92.1, 65.6, 41.5]

