"""
Ground-truth firewall — Person 1 (blueprint §8.2, M0-008, §23.6).

Proves that NO runtime module may import or open any file under:
  - any `expected/` directory
  - any file named `ground_truth.json`
  - any file matching `golden_*` in the test fixtures directory

This test is part of the `make guard` CI gate. If it fails, a PR is blocked.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

# Every runtime package that must never touch test ground-truth files.
# (blueprint §8.2 and M0-008: ingestion, detection, incident, topology/RCA,
#  evidence, playbook, and explanation packages are explicitly listed.)
RUNTIME_PACKAGES = (
    "ingestion",
    "detection",
    "incidents",
    "topology",
    "rca",
    "evidence",
    "playbooks",
    "explanation",
    "reviews",
    "audit",
    "orchestration",
    "simulator",
)

# Forbidden string tokens (case-insensitive scan of source text).
# These patterns indicate a runtime module is referencing test-only outputs.
FORBIDDEN_TOKENS = (
    "ground_truth",
    "golden_expected",
    "golden_anomalies",
    "golden_events",
    "golden_incident",
    "golden_investigation",
    "golden_review",
    "golden_audit",
    "/expected/",
    "\\expected\\",
    "expected/ground_truth",
    "tests/fixtures",
)


def test_runtime_packages_do_not_reference_expected_outputs() -> None:
    """No runtime .py file may reference ground-truth or golden test fixtures."""
    violations: list[str] = []
    app_root = ROOT / "backend" / "app"
    for package in RUNTIME_PACKAGES:
        pkg_dir = app_root / package
        if not pkg_dir.exists():
            continue  # Package not yet implemented — skip (not a violation)
        for path in pkg_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for token in FORBIDDEN_TOKENS:
                if token.lower() in text:
                    violations.append(
                        f"{path.relative_to(ROOT)} — references '{token}'"
                    )
                    break  # One report per file is enough
    assert violations == [], (
        "Runtime packages must never reference test ground-truth or golden fixtures:\n"
        + "\n".join(violations)
    )


def test_no_open_or_import_of_ground_truth_in_runtime() -> None:
    """Runtime packages must not call open() or Path.read_text() on ground-truth paths.

    This is a secondary check (simpler pattern scan). The primary structural check
    is test_runtime_packages_do_not_reference_expected_outputs above.
    """
    violations: list[str] = []
    app_root = ROOT / "backend" / "app"
    for package in RUNTIME_PACKAGES:
        pkg_dir = app_root / package
        if not pkg_dir.exists():
            continue
        for path in pkg_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            # Check for patterns like open("...ground_truth...") or Path("...golden_...")
            lower = text.lower()
            if "ground_truth" in lower or "golden_" in lower:
                violations.append(str(path.relative_to(ROOT)))
    assert violations == [], (
        "Runtime modules contain ground_truth or golden_ references:\n"
        + "\n".join(violations)
    )
