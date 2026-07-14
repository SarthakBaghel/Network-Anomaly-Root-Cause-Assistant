#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required"'
node -e 'const major=Number(process.versions.node.split(".")[0]); if (major !== 22) throw new Error(`Node 22 LTS is required; found ${process.version}`)'

python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock

.venv/bin/python scripts/build_scenario_bundle.py
.venv/bin/python scripts/build_handoff_fixtures.py
.venv/bin/alembic -c backend/alembic.ini upgrade head
.venv/bin/python scripts/seed_demo.py
.venv/bin/python scripts/generate_openapi.py

(
  cd frontend
  npm ci
  npm run generate-types
  npm run validate-fixtures
)

.venv/bin/python scripts/validate_milestone0.py --write-manifest
echo "Milestone-0 bootstrap complete"
