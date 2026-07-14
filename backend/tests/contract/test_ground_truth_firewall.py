from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_PACKAGES = (
    "ingestion",
    "detection",
    "incidents",
    "topology",
    "rca",
    "evidence",
    "playbooks",
    "explanation",
)
FORBIDDEN = ("ground_truth", "golden_expected", "golden_anomalies", "/expected/")


def test_runtime_packages_do_not_reference_expected_outputs() -> None:
    violations: list[str] = []
    app_root = ROOT / "backend" / "app"
    for package in RUNTIME_PACKAGES:
        for path in (app_root / package).rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            if any(token in text for token in FORBIDDEN):
                violations.append(str(path.relative_to(ROOT)))
    assert violations == []

