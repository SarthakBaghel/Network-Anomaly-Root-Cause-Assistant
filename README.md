# Network Anomaly Root-Cause Assistant

Hackathon prototype implementing the original contract in
[`BLUEPRINT.md`](./BLUEPRINT.md), plus the documented post-blueprint scenario
extensions described in
[`docs/reference-scenario-extensions.md`](./docs/reference-scenario-extensions.md)
and the post-blueprint
[`shift-handover report extension`](./docs/shift-handover-report-extension.md),
plus the stateless
[`Network Concepts Assistant`](./docs/network-concepts-assistant-extension.md).

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
make verify
```

`bootstrap.sh` creates `.venv`, installs the locked backend and frontend
dependencies, applies the Alembic migration, rebuilds deterministic fixtures,
and validates all Milestone-0 handoffs.

`make verify` is the final integration release gate. It runs every backend and
frontend boundary, generated-artifact check, and MSW-disabled live Playwright
flow twice. A production reset is executed against the live-test database
between passes, and the command fails unless both production replays produce
the same normalized semantic snapshot.

## Reference-derived scenarios

These are additive implementation extensions; they were not requirements in
the original blueprint. The simulator catalogue now includes six additional
deterministic demo paths:

- Network-path degradation (GAIA MicroSS + UNSW-NB15)
- DDoS / SYN flood (UNSW-NB15 + NSL-KDD)
- GAIA resource saturation
- Port scan / reconnaissance (UNSW-NB15 + NSL-KDD)
- HDFS DataNode failure (Loghub HDFS)
- Distributed trace latency and structure anomalies

The large local datasets stay under the ignored `/data/` directory. Runtime
events contain provenance and `REFERENCE_DERIVED` markers, but never dataset
outcome fields. The UI shows each scenario's reference datasets and
transformation version.

See the [extension specification](./docs/reference-scenario-extensions.md) for
the scenario-to-dataset, signal, detector, RCA, topology, and playbook mappings;
the meaning of deterministic execution; safety boundaries; and the recommended
demo flow.

To validate the local dataset bridges independently:

```bash
.venv/bin/python scripts/validate_dataset_pipeline.py
```

## Shift-handover report export

This is an additive post-blueprint demonstration feature. From an incident
page, an operator can download a timestamped Markdown or ReportLab-generated
PDF handover containing the immutable incident snapshot, timeline, top-ranked
hypothesis, evidence, operator actions, recommendations, and chronological
audit trail.

See the
[shift-handover extension record](./docs/shift-handover-report-extension.md)
for its scope, contracts, safety boundary, and verification record.

## Network Concepts Assistant

The lower-left **Network Concepts Assistant** answers one independent general
networking or observability question at a time through local Ollama. It receives
no page, incident, telemetry, file, or conversation-history context, and its
answer never participates in deterministic RCA.

Install and pull the optional model once, then use the normal combined run
command:

```bash
.venv/bin/python -m pip install -e "backend[llm]"
ollama pull qwen2.5:3b
./scripts/dev.sh
```

See the [assistant extension record](./docs/network-concepts-assistant-extension.md)
for its contract, stateless boundary, and failure behaviour.

## Optional local LLM explanation

Template explanations are the default and require no model. To enable the
optional validated Ollama narration after installing Ollama locally:

```bash
.venv/bin/python -m pip install -e "backend[llm]"
ollama pull qwen2.5:3b
EXPLANATION_MODE=llm OLLAMA_MODEL=qwen2.5:3b ./scripts/dev.sh
```

The application sends only the structured hypothesis, evidence, and playbook
bundle to `localhost:11434`. Ollama cannot alter ranks, evidence scores, or
evidence records. Invalid, stale, or unavailable LLM output automatically
retains the deterministic template explanation.

## Ownership

Implementation assignments and merge gates live in [`tasks.md`](./tasks.md).
Contract changes must first be recorded in
[`docs/api-decisions.md`](./docs/api-decisions.md). Runtime code must never read
`expected/`, `ground_truth.json`, or test golden-output fixtures.
