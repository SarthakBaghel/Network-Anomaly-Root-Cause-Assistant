from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
LIVE_DATABASE_URL = os.environ.get(
    "LIVE_E2E_DATABASE_URL",
    "sqlite:////tmp/network-anomaly-rca-playwright-live.db",
)


def _run(label: str, command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n[release gate] {label}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _pass(index: int, snapshot_path: Path) -> dict[str, Any]:
    print(f"\n========== RELEASE GATE PASS {index}/2 ==========", flush=True)
    python = sys.executable
    _run(
        "production fixture replay and semantic capture",
        [
            python,
            "scripts/build_handoff_fixtures.py",
            "--check",
            "--semantic-output",
            str(snapshot_path),
        ],
    )
    _run(
        "production OpenAPI drift check",
        [python, "scripts/generate_openapi.py", "--check"],
    )
    _run(
        "P2 generated TypeScript drift check",
        ["npm", "run", "check-generated-types"],
        cwd=FRONTEND,
    )
    _run(
        "contracts, catalogues, fixture generators, and runtime firewall",
        [python, "scripts/validate_milestone0.py"],
    )
    _run(
        "production pipeline, failure durability, and reset/replay boundaries",
        [
            python,
            "-m",
            "pytest",
            "backend/tests/integration/test_production_backend_pipeline.py",
            "-q",
        ],
    )
    _run(
        "remaining backend suite",
        [
            python,
            "-m",
            "pytest",
            "backend/tests",
            "--ignore=backend/tests/integration/test_production_backend_pipeline.py",
            "-q",
        ],
    )
    _run("frontend unit and contract suite", ["npm", "test"], cwd=FRONTEND)
    _run("frontend production build", ["npm", "run", "build"], cwd=FRONTEND)
    live_env = os.environ.copy()
    live_env["LIVE_E2E_DATABASE_URL"] = LIVE_DATABASE_URL
    _run(
        "MSW-disabled live Playwright golden path",
        ["npm", "run", "e2e:live"],
        cwd=FRONTEND,
        env=live_env,
    )
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def _reset_between_passes() -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = LIVE_DATABASE_URL
    _run(
        "mandatory production reset between complete passes",
        [sys.executable, "scripts/reset_release_state.py"],
        env=env,
    )


def _digest(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="network-rca-release-") as directory:
        first_path = Path(directory) / "pass-1.json"
        second_path = Path(directory) / "pass-2.json"
        first = _pass(1, first_path)
        _reset_between_passes()
        second = _pass(2, second_path)

        if first != second:
            first_text = json.dumps(first, indent=2, sort_keys=True).splitlines()
            second_text = json.dumps(second, indent=2, sort_keys=True).splitlines()
            diff = "\n".join(
                difflib.unified_diff(
                    first_text,
                    second_text,
                    fromfile="release-pass-1",
                    tofile="release-pass-2",
                    lineterm="",
                )
            )
            raise SystemExit(
                "release gate failed: semantic results differ between passes\n" + diff
            )

        digest = _digest(first)
        print("\n========== FINAL RELEASE GATE PASSED ==========", flush=True)
        print("complete passes: 2", flush=True)
        print("production resets between passes: 1", flush=True)
        print(f"identical semantic digest: sha256:{digest}", flush=True)


if __name__ == "__main__":
    main()
