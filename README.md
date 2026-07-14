# Network Anomaly Root-Cause Assistant

Hackathon prototype implementing the contract in
[`NETWORK_ANOMALY_RCA_PROTOTYPE_BLUEPRINT.md`](./NETWORK_ANOMALY_RCA_PROTOTYPE_BLUEPRINT.md).

## Prerequisites

- Python 3.12 or newer
- Node.js 22 LTS (`nvm use` reads `.nvmrc`)
- npm 10 or newer

## Commands

```bash
cp .env.example .env       # optional; defaults work without it
./scripts/bootstrap.sh
./scripts/dev.sh
python3 scripts/build_scenario_bundle.py --check
python3 scripts/validate_milestone0.py
```

`bootstrap.sh` creates `.venv`, installs the locked backend and frontend
dependencies, applies the Alembic migration, rebuilds deterministic fixtures,
and validates all Milestone-0 handoffs.

## Ownership

Implementation assignments and merge gates live in [`tasks.md`](./tasks.md).
Contract changes must first be recorded in
[`docs/api-decisions.md`](./docs/api-decisions.md). Runtime code must never read
`expected/`, `ground_truth.json`, or test golden-output fixtures.
