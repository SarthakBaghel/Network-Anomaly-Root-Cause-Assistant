from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    subprocess.run([sys.executable, "scripts/validate_milestone0.py"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-m", "pytest"], cwd=ROOT / "backend", check=True)
    print("Milestone-0 demo foundation verified; feature golden path is implemented by workstream owners.")


if __name__ == "__main__":
    main()

