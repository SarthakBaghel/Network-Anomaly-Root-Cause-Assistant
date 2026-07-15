from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    destination = BACKEND / "openapi.json"
    content = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not destination.exists() or destination.read_text(encoding="utf-8") != content:
            raise SystemExit("backend/openapi.json is stale; run make generate-types")
        print("validated backend/openapi.json against the production FastAPI app")
        return
    destination.write_text(content, encoding="utf-8")
    print(f"generated {destination.relative_to(ROOT)} from the production FastAPI app")


if __name__ == "__main__":
    main()
