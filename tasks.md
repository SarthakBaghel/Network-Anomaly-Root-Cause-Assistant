# Network Anomaly Root-Cause Assistant — Team Task Board
> **Authority:** [NETWORK_ANOMALY_RCA_PROTOTYPE_BLUEPRINT.md](./NETWORK_ANOMALY_RCA_PROTOTYPE_BLUEPRINT.md) (v1.4) is the implementation source of truth.
> If `design.md`, `Ideation.md`, code, or this file conflicts with the blueprint, **the blueprint wins** until a reviewed change is recorded in `docs/api-decisions.md`.

> **Purpose:** This is the executable work board for a five-person team. Each artifact has one accountable owner, named consumers, acceptance checks, and a handoff point. “Owner” means merge responsibility; another person may review, but must not independently create a competing version.

---

## Status Key & Rules

| Symbol | Meaning |
|--------|---------|
| `[ ]` | Not started |
| `[/]` | In progress |
| `[x]` | Done / merged to `main` |
| `[!]` | Blocked — needs Person 1 decision before continuing |

**Golden rule:** Complete your current task before picking up the next. If blocked, flag it in the team channel immediately — do NOT silently work around a contract.

**Key libraries per person** are listed at the top of each section. Install everything from the lock file only; do not pin directly.

**Branch rule:** The first 30 minutes freeze contracts, IDs, and ownership. After that, create small feature branches immediately (`feature/p1-*` … `feature/p5-*`). Rebase before handoff, keep generated files in the same commit as their source, and merge only through the CI gates below.

**Definition of done for every task:** implementation + automated test + any fixture/schema update + short handoff note. “Works on my machine” is not done.

---

## ⚡ First 30 Minutes — All Five Together (Milestone 0 Kickoff)

> Do not wait for the full backend. Freeze the shared contracts below, then start fixture-first work in parallel. Person 1 drives the decisions; every person confirms their consumer test can read the handoff they need.

- [x] **ALL-01**: Read blueprint §§1–7, §10, §22, and your workstream section before writing feature code.
- [x] **ALL-02**: Agree golden scenario is the **disabled gateway rate limiter** (blueprint §10.3). The second scenario is priority-P1 scope — do not build it until the golden path is fully green.
- [x] **ALL-03**: Confirm tech stack: Python 3.12+, FastAPI, Pydantic v2, synchronous SQLAlchemy 2 + SQLite, Alembic, Node 22 LTS, React + TypeScript + Vite, Tailwind CSS, `@xyflow/react`, Recharts, Vitest, and `@playwright/test`. Record any blueprint/tooling version drift in `docs/api-decisions.md` before the first merge.
- [x] **ALL-04**: Freeze entity IDs — these are locked and used by every fixture:
  ```
  api-gateway-01, checkout-api-01, payment-api-01, payment-db-01, auth-api-01
  ```
- [x] **ALL-05**: Verify the `92.1` score from the frozen factor rubric (blueprint §14.3 table) before anyone touches ranking code.
- [x] **ALL-06**: Freeze these implementation resolutions in `docs/api-decisions.md`: seeded historical similarity is P0 (required for `92.1`); simulator records carry `scenario_id`; metrics/config records enter normalization with source severity `0.0`; the nine detector anomalies and separate non-opening config context marker have an explicit fixture representation; attached and excluded event evaluations are stored separately; runtime code may never import `expected/` or `ground_truth/` files.
- [x] **ALL-07**: Person 1 creates the repo skeleton and contract examples; everyone verifies their own consumer test can load the relevant example. `bootstrap.sh` may mature during Hour 0–2 and must be green at Milestone 0.
- [x] **ALL-08**: Agree this fixture-first handoff order and post links/checksums in the team channel:
  1. P1: Pydantic contracts, OpenAPI examples, fixed entity/scenario IDs.
  2. P3: raw source examples, provenance bundle, `golden_events.jsonl`, `golden_anomalies.json`.
  3. P4: valid topology and static `golden_expected_analysis.json`, then `golden_incident_bundle.json`.
  4. P5: `golden_investigation_response.json`.
  5. P2: route + `data-testid` manifest and mock-backed pages.

> **Kickoff verification:** `./scripts/bootstrap.sh` and `make verify` are green under Node 22. Artifact links and SHA-256 values are checked into [`docs/handoff-manifest.md`](./docs/handoff-manifest.md); frozen resolutions are in [`docs/api-decisions.md`](./docs/api-decisions.md).
>
> The checkmarks record the repository/lead freeze. Each human teammate must still personally acknowledge the reading requirement, their resolver responsibility, and the handoff manifest in the team's communication channel before merging feature work.

### Frozen ownership map

| Shared artifact | Accountable owner | Consumers |
|---|---|---|
| Contracts, DB schema, OpenAPI, migrations | Person 1 | All |
| Raw simulator bundle, provenance, adapter fixtures, detector rules, golden events/anomalies | Person 3 | P1, P4, P5 |
| Topology, hypothesis/symptom catalogues, incident bundle, expected analysis | Person 4 | P1, P2, P5 |
| Playbooks, evidence, explanations, investigation response, review/audit examples | Person 5 | P1, P2 |
| Frontend routes, generated-type consumption, test-ID manifest, UI tests | Person 2 | P1 integration |
| Analysis transaction/publication, reset orchestration, end-to-end CI/demo | Person 1 | All |

---

## 🔴 Person 1 — Foundation / Contracts / Integration / Demo (WS0 + WS6)

> **Key libraries:** `fastapi`, `pydantic>=2,<3`, `sqlalchemy>=2,<3` (synchronous SQLite), `alembic`, `uvicorn`, `python-dotenv`, `pytest`, `httpx` (test client), `black`, `ruff`

> **First deliverable (Hour 0–2):** App boots, DB migrates, `/api/v1/health` and `/api/v1/ready` respond, all fixtures validate, every teammate can pull and run `bootstrap.sh` successfully.

### Phase 0 — Contracts & Scaffold (Hours 0–2 — UNBLOCKS CONSUMERS)

- [x] **P1-01**: Create repo skeleton matching blueprint §6 exactly:
  ```
  backend/app/{contracts,db,api,orchestration,ingestion,simulator,detection,incidents,topology,rca,evidence,playbooks,explanation,reviews,audit,fixtures}
  frontend/src/{api,contracts,pages,components,features}
  scripts/, docs/
  ```
  ✅ All directories exist and match blueprint §6.

- [x] **P1-02**: Create `backend/app/contracts/` — all fields, enums, constraints, examples, and nullability rules from blueprint §7. These are **frozen**; no teammate edits without §1.3 review. At minimum include:
  - `Modality`, `EventStatus`, `IncidentStatus`, `EvidenceKind`, `ReviewDecision`, `AuditActorType`, `TopologyRelation`, `AnalysisRunStatus` enums
  - `CanonicalEvent` (all fields from §7.2, including `signal_name/value/unit`, `trace_or_session_id`, `quality_flags`, redaction)
  - `AnomalyRecord` (§7.3 — `detector_id`, `context_only`, `can_open_incident`, `features`)
  - `IncidentSummary` (§7.4 — including `current_analysis_run_id`, `top_hypothesis_id`, `confirmed_hypothesis_id`)
  - `Hypothesis` (§7.5 — `factor_scores` dict, `evidence_score` 0–100 float, `evidence_coverage`)
  - `EvidenceItem` (§7.6 — `kind`, `reason_code`, nullable `source_event_id`)
  - `ReviewRecord` (§7.7 — including `analysis_run_id`, `client_action_id`, `requested_evidence_id` nullable)
  - `AnalysisRun` (§7.8 — `input_fingerprint`, `algorithm_version`, `status` transitions)
  - Generate JSON Schema/OpenAPI examples and tests so omitted fields fail visibly rather than silently defaulting.
  ✅ All Pydantic models, enums, and OpenAPI examples in `backend/app/contracts/`. Contract tests green.

- [x] **P1-03**: Create `backend/app/config.py` with all frozen settings from blueprint §4.1:
  ```python
  DATABASE_URL = "sqlite:///./network_anomaly_rca.db"
  EXPLANATION_MODE = "template"   # "llm" is optional priority-P1 scope
  SIMULATOR_SEED = 20260714
  SIMULATOR_METRIC_INTERVAL_SECONDS = 10
  DETECTOR_WINDOW_SECONDS = 300
  DETECTOR_MIN_BASELINE_POINTS = 20
  METRIC_ZSCORE_THRESHOLD = 3.0
  ANOMALY_THRESHOLD = 0.75
  INCIDENT_OPEN_THRESHOLD = 0.75
  INCIDENT_LOOKBACK_SECONDS = 300
  INCIDENT_IDLE_WINDOW_SECONDS = 300
  INCIDENT_MAX_TOPOLOGY_HOPS = 2
  INCIDENT_ATTACHMENT_THRESHOLD = 0.40
  DUPLICATE_BUCKET_SECONDS = 10
  EVENT_BATCH_MAX_ITEMS = 100
  EVENT_MAX_PAYLOAD_BYTES = 65536
  FRONTEND_POLL_INTERVAL_MS = 1500
  ```
  Startup must validate settings and fail with a concrete error on bad values (blueprint §4.1).

- [x] **P1-04**: Create `backend/app/db/models.py` — SQLAlchemy 2 ORM models for all tables in blueprint §8.1:
  - `events`, `quarantined_events`, `collapsed_event_groups`
  - `anomalies`, `entities`, `topology_edges`
  - `incidents`, `incident_events`, `incident_event_evaluations`, `analysis_runs`
  - `hypotheses`, `evidence`, `playbook_recommendations`, `explanations`
  - `reviews`, `audit_logs`, `historical_incidents`
  - Enable `PRAGMA foreign_keys=ON` on every connection
  - `incident_events` contains attached events only; `incident_event_evaluations` records every considered event with `decision=attached|excluded`, score, and reason codes. This is the agreed §1.3 clarification for auditable exclusions.
  - All integrity constraints from §8.2 enforced

- [x] **P1-05**: Create initial Alembic migration (`alembic revision --autogenerate`) and verify `alembic upgrade head` runs cleanly from scratch.
  ✅ Migration `2eff20be3718 initial_contract_schema` applied. `alembic upgrade head` clean.

- [x] **P1-06**: Create `backend/app/db/repositories/` — one repository class per domain, with interfaces only (no SQL in feature modules). Feature owners define required methods here:
  - `EventRepository`, `QuarantineRepository`, `AnomalyRepository`
  - `IncidentRepository`, `AnalysisRunRepository`
  - `HypothesisRepository`, `EvidenceRepository`, `ReviewRepository`, `AuditRepository`
  ✅ All 6 repository files created with full method signatures. All imports verified.

- [x] **P1-07**: Create `backend/app/main.py` — FastAPI app with all stubs returning example payloads:
  - `GET /api/v1/health` → `{"status": "ok"}`
  - `GET /api/v1/ready` → component-level readiness (DB, catalogues, topology, orchestrator)
  - All endpoints from blueprint §18.1, §18.2, §18.3 stubbed with frozen example JSON
  ✅ Includes lifespan startup handler (topology load + historical seed on first boot). Readiness reports real orchestrator status.

- [x] **P1-08**: Create catalogue schemas/loaders/version validators in `backend/app/fixtures/`. Startup rejects a missing file, unsupported `schema_version`, duplicate ID, dangling reference, invalid topology edge, or incompatible content version. Content ownership is not shared:
  - P3 owns `detector_rules.yaml`.
  - P4 owns `topology.json`, `hypotheses.yaml`, and `symptom_families.yaml`.
  - P5 owns `playbooks.yaml`.
  - P1 owns loader interfaces, validation, startup wiring, and cross-catalogue referential-integrity tests.

- [x] **P1-09**: Publish the handoff contract pack (not the feature-owned fixture content): OpenAPI JSON, JSON Schemas, fixed IDs, common error envelope examples, `analysis_run_id` consistency example, and `make validate-fixtures`. Validate fixture content supplied by P3/P4/P5 without taking over ownership.
  ✅ `openapi.json`, `docs/handoff-manifest.md`, and `docs/api-decisions.md` are synchronized. Milestone 0 validator: 16 deterministic + 7 handoff artifacts validated.

- [x] **P1-10**: Seed `historical_incidents` as P0 with one gateway-rate-limit incident per §20.2 (this resolution preserves the frozen `92.1` score):
  - Same confirmed cause as the golden scenario, half (not all) of the fingerprint features
  - Fixed timestamp and IDs — deterministic `historical_similarity = 0.5`
  - Store in `scripts/seed_demo.py`
  ✅ `hist_gateway_rate_limit_001` seeded via `seed_demo.py`; re-seeded automatically on reset and startup.

- [x] **P1-11**: Write `backend/tests/contract/test_contracts.py` — validates all fixture JSON against Pydantic models. This is the gate: if this test breaks, the PR is blocked.
  ✅ 27/27 contract tests and 2/2 dedicated ground-truth-firewall tests green.

- [x] **P1-12**: Create `scripts/bootstrap.sh` (idempotent), `scripts/dev.sh`, `scripts/seed_demo.py`, `scripts/verify_demo.py` as described in §6.1.
  ✅ All scripts present. `bootstrap.sh` idempotent.

- [x] **P1-13**: Implement `AnalysisOrchestrator` and atomic publisher in `backend/app/orchestration/` (§5.2):
  - Single in-process analysis lock
  - Sequential: `ingest → detect → attach → RCA → publish atomically`
  - `input_fingerprint` computation: `SHA-256(sorted incident event IDs and canonical content hashes | topology fixture version | catalogue versions | algorithm version)`
  - Idempotent no-op if fingerprint matches current run
  - Build candidate/evidence/recommendation/explanation outputs against one run ID; validate them; then mark the prior run `superseded` and switch `incident.current_analysis_run_id` in one transaction
  - On failure: persist `status=failed` with sanitized reason + `PIPELINE_STAGE_FAILED`; leave the prior run current
  ✅ `orchestration/orchestrator.py` + `reset_service.py` implemented. Protocol interfaces defined for P3/P4/P5; accepted-event runtime handoff and atomic publication tests are green.

### Phase 1 — Integration Gating (Ongoing throughout day)

- [x] **P1-14 — Gate: Milestone 0** (~Hour 2): All contracts validate, both apps boot, health/ready endpoints respond, and each fixture owner has a passing producer/consumer contract test. Feature work already in progress may continue after sign-off.
  ✅ **SIGNED OFF.** `validate_milestone0.py` is green (16 deterministic + 7 handoff artifacts). Health + ready endpoints respond with all components ready.

- [x] **P1-15 — Gate: Milestone 1** (~Hour 6): Person 3's pipeline produces events; quarantine and collapse work; per-source counters visible. Sign off.
  ✅ **SIGNED OFF.** Ingestion adapters, alarm collapsing, and rolling Z-score detectors are fully integrated and verified (all 74/74 unit/integration tests green).

- [x] **P1-16 — Gate: Milestone 2** (~Hour 10): Scenario opens one incident with typed topology attachment and excluded auth warning. Sign off.
  ✅ **SIGNED OFF.** Incident manager correctly scores and groups anomalies. Lookback attaches configuration change at T+0, and excludes the auth warning at T+120 due to trace mismatch and symptom family incompatibility.

- [x] **P1-17 — Gate: Milestone 3** (~Hour 14): Three ranked candidates, factor scores, four evidence categories, immutable analysis run published. Sign off.
  ✅ **SIGNED OFF.** RCA Engine ranks Configuration Regression, DoS, and DB Connection Exhaustion. Computes transparent evidence scores and coverage, and publishes immutable AnalysisRun snapshots.

- [x] **P1-18 — Gate: Milestone 4** (~Hour 18): Full P0 path end to end — investigation page, playbooks, review, audit. Sign off. No new features after this.
  ✅ **SIGNED OFF.** Investigation details, playbooks, audits, and reviews are fully wired and functional through `/incidents/{id}/investigation` and `/incidents/{id}/review` endpoints.

- [x] **P1-19 — Gate: Milestone 5** (~Hour 22): `make verify` green twice after reset/replay. Demo rehearsal done. Tag commit as demo candidate.
  ✅ **SIGNED OFF.** Recovery rehearsal completed between two green `make verify` runs. Final gate: 27 contract tests, 2 firewall tests, 197 backend tests passed (34 optional external-dataset skips), 14 frontend tests, and a production frontend build.

### Phase 2 — Docs / Demo

- [x] **P1-20**: Write `docs/api-decisions.md` — document any contract decisions made during the build.
  ✅ M0-001 through M0-014 recorded in `docs/api-decisions.md`.
- [x] **P1-21**: Write `docs/demo-script.md` based on blueprint §27 — step-by-step talking points with fallback paths for each failure mode.
  ✅ Done. Contains step-by-step presentation script, talking points, and failure fallbacks.
- [x] **P1-22**: Implement `ResetService` and `POST /api/v1/simulator/reset` orchestration (§5.2): stop via P3's simulator hook, acquire the analysis lock, clear demo rows in FK-safe order, reload topology + seeded history, call P3's deterministic clock/state reset hook, and write one `DEMO_RESET` audit entry. P3 owns emitter state; P1 owns the cross-domain transaction and API wiring.
  ✅ `POST /simulator/reset` → 200 + DEMO_RESET audit entry. FK-safe purge order. `SimulatorResetHook` protocol defined for P3.

- [x] **P1-23**: Create locked dependency files, root `Makefile`, and CI commands: `make bootstrap`, `make validate-fixtures`, `make test`, `make generate-types`, `make build`, `make verify`. Add a test/lint rule proving runtime modules never import or open any `expected/`, `ground_truth`, or test golden-output file.
  ✅ Done. Root Makefile wired with all 6 targets. Firewall test scans all runtime packages. Dependency lockfiles validated.

---

## 🟠 Person 2 — Frontend / Dashboard (WS5)

> **Key libraries:** `react`, `typescript`, `vite`, `tailwindcss`, `@tailwindcss/vite`, `@xyflow/react` (topology graph), `recharts` (timeline/metrics), `axios` (API client), `vitest`, `@testing-library/react`, `@playwright/test`, `msw` (Mock Service Worker for local dev)

> **First deliverable (Hour 0–2):** Mocked investigation page rendering `golden_investigation_response.json` with all panels visible — no backend needed yet.

### Phase 0 — Scaffold & Mocks (Hours 0–3)

- [x] **P2-01**: Bootstrap with Node 22 LTS and commit the lock file:
  ```bash
  npm create vite@latest frontend -- --template react-ts
  cd frontend
  npm install @xyflow/react recharts axios msw
  npm install -D tailwindcss @tailwindcss/vite vitest @testing-library/react @testing-library/jest-dom @playwright/test
  npx playwright install chromium
  ```
  Configure the Tailwind Vite plugin. In the global CSS, import `tailwindcss` first and `@xyflow/react/dist/style.css` after it. Do not install the retired `react-flow` package or depend on globally installed tooling.

- [x] **P2-02**: Create `frontend/src/api/client.ts` — typed axios wrapper reading all responses through OpenAPI-generated types (regenerated by `make generate-types`). Components never call `fetch` directly.
  - Base URL from env var; default `http://localhost:8000/api/v1`
  - All responses type-checked against generated contracts
  - Common error envelope (`code`, `message`, `details`) surfaces to UI

- [x] **P2-03**: Create `frontend/src/api/` — one file per domain:
  - `events.ts` → `GET /events`, `GET /events/{id}`, `GET /quarantine`
  - `incidents.ts` → `GET /incidents`, `GET /incidents/{id}/investigation`, `POST /incidents/{id}/review`, `GET /incidents/{id}/audit`
  - `simulator.ts` → `POST /simulator/start`, `POST /simulator/stop`, `POST /simulator/reset`, `POST /simulator/scenarios/{id}/trigger`, `GET /simulator/status`
  - `topology.ts` → `GET /topology?incident_id=`, `GET /topology/path`, `GET /topology/blast-radius/{id}`

- [x] **P2-04**: Create `frontend/src/hooks/usePolling.ts` — generic hook with `setInterval` at `FRONTEND_POLL_INTERVAL_MS` (1500 ms). Discard responses with `generated_at` older than the last rendered timestamp. Replace entire investigation snapshot when `analysis_run_id` changes (never merge old+new run data).

- [x] **P2-05**: Set up Mock Service Worker (`msw`) with handlers serving P5's `golden_investigation_response.json` and P3's golden event examples — so the full UI renders before any backend is ready. Assert the fixture validates against P1's generated type before rendering.

- [x] **P2-06**: Freeze `data-testid` manifest in `frontend/src/test-fixtures/testid-manifest.ts`. Every interactive element gets a stable, unique `data-testid` (Playwright depends on these — see blueprint §22.2). Examples:
  ```
  simulator-start-btn, simulator-reset-btn, scenario-trigger-btn
  incident-list, incident-row-{id}
  investigation-panel, hypothesis-row-{id}, evidence-panel
  hypothesis-confirm-btn, hypothesis-reject-btn, evidence-request-btn
  topology-graph, timeline-panel, audit-trail-panel
  source-health-{source-name}
  ```

### Phase 1 — Two Routes (Hours 2–12)

> Blueprint §19.6: P0 uses exactly two routes.

**Route 1: `/` — Operations Overview**

- [x] **P2-07 — Source Health Bar**: Five adapter cards showing `ready|error`, last ingest time, and `accepted / collapsed / quarantined` counts for each:
  - `simulator.prometheus` (metrics)
  - `simulator.syslog` (logs)
  - `simulator.alertmanager` (alerts)
  - `simulator.config_audit` (config changes)
  - `fixture.cmdb_topology` (topology fixture version + load status)

- [x] **P2-08 — Simulator Controls**: Start / Stop / Reset buttons + scenario dropdown → `POST /simulator/scenarios/{id}/trigger`. Show virtual clock and scenario active state. Buttons are idempotent; disabled while transitioning.

- [x] **P2-09 — Recent Anomalies Table**: Last 20 anomaly records with entity, type, score, detector ID. Updates on each poll.

- [x] **P2-10 — Incident List**: Severity badge, title, affected entities, start time, status chip. Clicking a row navigates to `/incidents/:incidentId`.

**Route 2: `/incidents/:incidentId` — Incident Investigation**

> Entire page sourced from a **single** `GET /incidents/{id}/investigation` snapshot. The UI must discard a response if a newer `analysis_run_id` is already rendered (§18.5).

- [x] **P2-11 — Incident Header**: Title, severity, status, affected entities, `analysis_run_id` shown in small text.

- [x] **P2-12 — Incident Timeline** (blueprint §19.3):
  - One aligned time axis
  - Four lanes: metric / log / alert / config change
  - Candidate-relevant events visually distinct (e.g. solid colour) from unrelated/excluded events (muted)
  - Event click → opens raw record modal showing `CanonicalEvent` + `attachment_score` + `attachment_reasons`
  - Use `recharts` `ComposedChart` with custom dot rendering per lane

- [x] **P2-13 — Topology Impact Graph** (blueprint §19.4, §13.3):
  - Use `@xyflow/react` with directed, typed edges
  - Four node states coloured distinctly: `suspected_root`, `primary_affected`, `impact_path`, `blast_radius`
  - Edge labels showing `relation_type`: `depends_on` or `sends_traffic_to`
  - Legend explaining BOTH edge types and traversal direction used by the active hypothesis
  - Never implies dependency arrows use traffic-flow traversal rules (§10.3)
  - Data only from the topology field in the single investigation snapshot already loaded by the page; do not make a second topology request that could mix analysis runs

- [x] **P2-14 — Ranked Hypotheses Panel**: Ordered list from `hypotheses[]` in the investigation snapshot:
  - Rank badge, candidate entity name, hypothesis type
  - **Evidence score** bar (0–100) — label exactly "Evidence score", never "confidence" or "causal probability"
  - Evidence coverage: `available / expected` shown (e.g. "6/7 expected evidence requirements available")
  - Expandable factor breakdown table with all 8 factors

- [x] **P2-15 — Evidence Explorer** (blueprint §15.1, four categories):
  - Four collapsible sections: **Verified observed facts** / **Correlated signals** / **Conflicting evidence** / **Missing evidence**
  - `observed` labelled "Verified observed fact" with tooltip: *"Confirms the record and value were observed; does not confirm causation"*
  - `conflicting` shown in amber — weakens or contradicts
  - `missing` shown as an explicit collection request (from catalogue template, e.g. "Obtain WAF decision logs for 09:25–09:35 UTC")
  - Each item clickable → raw `CanonicalEvent` modal (or collection-request description for missing)

- [x] **P2-16 — Playbook / Diagnostic Recommendations Panel**: Safe suggestions per hypothesis; label **“Catalogue recommendation — not executed”**; `step_id` visible; `risk_level` and `requires_human_approval` indicated. Do not imply the deterministic catalogue is an AI action.

- [x] **P2-17 — Human Review Controls** (blueprint §20.1):
  - **Confirm** / **Reject** / **Request Evidence** buttons per hypothesis
  - Evidence-request button enabled only for `missing`-evidence items; sends `requested_evidence_id`
  - Each action POSTs with a unique `client_action_id` (UUID generated client-side per click); idempotent on retry
  - On `409 STALE_ANALYSIS` → show "Analysis updated, refresh the page" banner
  - On `409 REVIEW_CONFLICT` → show "Decision already recorded"
  - On Confirm: hypothesis label changes to **"Confirmed root cause"** — the only place this wording appears (blueprint §5 wording rules)
  - Disable buttons and show spinner while request is in flight

- [x] **P2-18 — Audit Trail Panel**: Table from `GET /incidents/{id}/audit`; timestamp, actor type, action code, object; filterable. Append-only — no delete UI.

### Phase 2 — States & Polish (Hours 12–18)

- [x] **P2-19**: All explicit UI states required by blueprint §19.5:
  - Baseline running, no incident yet
  - Scenario not triggered
  - Explanation validation fallback (template used instead of LLM)
  - Quarantine warning banner when any source has quarantined count > 0
  - Missing evidence displayed as a concrete collection request (never just "unknown")
  - API error banner (frozen error code + message; no stack traces)
  - Stale-analysis banner when poll returns a newer `analysis_run_id`

- [x] **P2-20**: Accessibility: severity/status communicated with text+icon (not colour alone); review controls keyboard accessible; ARIA labels on all interactive elements.

- [x] **P2-21**: Write `frontend/tests/` component tests with Vitest + RTL for:
  - Evidence Explorer renders all four categories
  - Confirm action disables button, calls API with `client_action_id`
  - Stale-analysis poll response is discarded when `analysis_run_id` is older
  - Timeline correctly separates attached vs excluded events

- [x] **P2-22**: Own `frontend/tests/e2e/golden_path.spec.ts` and all selectors/assertions for the Playwright golden path in blueprint §25.4, using the `data-testid` manifest only. P1 owns the cross-project runner, process startup/reset, CI wiring, and final green sign-off.

### Phase 3 — Pitch Deck (After Milestone 4)

- [x] **P2-23**: 10-slide deck:
  1. Problem statement (verbatim from ProblemStatement.md)
  2. System architecture (Mermaid from blueprint §5)
  3. Five source adapters + normalization
  4. Analysis pipeline: detection → incident → RCA → evidence
  5. Evidence tiers + conflicting evidence (the key differentiator)
  6. Live demo screenshots/video
  7. Factor scoring table with frozen `92.1` example
  8. Actually implemented (P0) vs future (P2)
  9. Dataset strategy: reference-only; simulator is the runtime source
  10. Q&A

---

## 🟡 Person 3 — Event Pipeline / Ingestion / Detection (WS1 + WS2A)

> **Key libraries:** `fastapi`, `pydantic>=2,<3`, `sqlalchemy>=2,<3` (synchronous SQLite), `numpy`, `pandas`, `hashlib` (stdlib), `zoneinfo` (stdlib), `ulid-py` (deterministic IDs), `pytest`

> **First deliverable (Hours 0–4):** provenance-tagged raw multimodal scenario bundle + `golden_events.jsonl` + `golden_anomalies.json`, with one valid and invalid raw payload per adapter. Publish static fixtures early; Person 4 does not wait for the runtime emitter/detector implementation.

### Phase 0 — Handoff Fixtures First (Hours 0–2)

- [x] **P3-00**: Build blueprint v1.4's provenance-safe bundle under `backend/app/fixtures/`:
  - `reference_profiles/network_profile.json` and `reference_profiles/log_templates.yaml`
  - `scenarios/gateway_rate_limit/inputs/{metrics,logs,alerts,config_changes}.jsonl`; every referenced entity must exist in P4's topology
  - `scenarios/gateway_rate_limit/provenance.json` with source file/hash, derivation script version, seed, generated-at value, and output hashes
  - `scenarios/gateway_rate_limit/expected/ground_truth.json` for tests only; runtime replay accepts `inputs/` only
  - `scripts/build_network_profile.py` reproduces byte-identical outputs from the checked-in source profile and seed
  - Add a provenance/ID/hash manifest test; coordinate with P1's runtime-import guard

- [x] **P3-01**: Create `backend/tests/fixtures/source_adapters/` — freeze the four raw source-schema shapes from blueprint §9.1.1 exactly:
  - `valid_prometheus_sample.json` — Prometheus metric sample
  - `invalid_prometheus_sample.json` — missing `entity_id` in `labels`
  - `valid_syslog_record.json` — syslog with `trace_id`
  - `invalid_syslog_record.json` — missing `host`
  - `valid_alertmanager_alert.json`
  - `invalid_alertmanager_alert.json` — missing `startsAt`
  - `valid_config_audit.json` — with `change_ticket`
  - `invalid_config_audit.json` — missing required `target_entity_id` (do not invent an `old_value != new_value` validation rule unless it is approved as a contract change)

- [x] **P3-02**: Create `backend/tests/fixtures/golden_events.jsonl` from the raw reference bundle — the complete baseline stream (at least 20 samples for every scored metric signal) plus all events in the nine post-trigger timestamp groups from §10.3, with exact:
  - `event_id` (deterministic from `SIMULATOR_SEED`)
  - `source_record_id`
  - `entity_id`
  - `modality`
  - `signal_name`, `signal_value`, `unit` for metrics
  - `trace_or_session_id=scenario_gateway_rate_limit_001` for golden-scenario records (except the deliberately unrelated auth warning)
  - `quality_flags=["SIMULATED"]` and provenance metadata retained in `raw_payload`
  - All timestamps relative to a fixed `T=2026-07-14T09:30:00.000Z`
  - A generator test compares this canonical output with the adapter output produced by replaying the raw bundle

### Phase 1 — Simulator (Hours 1–5)

- [x] **P3-03**: Create `backend/app/simulator/engine.py` — deterministic seed-based emitter:
  - `SIMULATOR_SEED = 20260714`
  - Emits baseline events (at least 20 metric samples per signal over 5 minutes)
  - Supports `start`, `stop`, `reset`, `pause`, `resume`
  - Virtual clock advancing `SIMULATOR_METRIC_INTERVAL_SECONDS` per tick
  - Never writes directly to analysis tables — always calls ingestion

- [x] **P3-04**: Create four distinct emitter classes in `backend/app/simulator/emitters/`:
  - `PrometheusEmitter` — emits metric samples with `sample_id`, `observed_at`, `metric`, `value`, `unit`, `labels`
  - `SyslogEmitter` — emits log records with `record_id`, `host`, `facility`, `level`, `code`, `message`, `trace_id`
  - `AlertmanagerEmitter` — emits alerts with `fingerprint`, `startsAt`, `status`, `labels`, `annotations`
  - `ConfigAuditEmitter` — emits config changes with `change_id`, `changed_at`, `target_entity_id`, `actor`, `config_key`, `old_value`, `new_value`, `change_ticket`
  - Each emitter has a distinct source name (e.g. `simulator.prometheus`) and different payload shape
  - Every raw record carries a common transport envelope containing `scenario_id`, `emitted_at`, and provenance metadata; the payload shape inside that envelope remains source-specific

- [x] **P3-05**: Implement the golden scenario timeline exactly (blueprint §10.3):
  ```
  T+0s:   api-gateway-01  config_change  rate_limit.enabled: true→false  (change_ticket: CHG-DEMO-001)
  T+30s:  api-gateway-01  metric         forwarded_requests_per_second=7800 (was 2400)
  T+30s:  api-gateway-01  metric         active_connections_total (spike)
  T+30s:  api-gateway-01  metric         connection_utilization (spike)
  T+40s:  api-gateway-01  metric         tcp_resets_total (increase)
  T+40s:  api-gateway-01  metric         tcp_retransmissions_total (increase)
  T+45s:  api-gateway-01  alert          HighForwardedRequestRate (critical; one combined gateway alert)
  T+60s:  checkout-api-01 metric         p95_latency (increase)
  T+75s:  payment-api-01  log            UPSTREAM_CONNECTION_TIMEOUT (trace: scenario_gateway_rate_limit_001)
  T+90s:  checkout-api-01 alert          HighCheckoutErrorRate
  T+100s: payment-db-01   metric         db_connection_utilization=NORMAL (conflicting evidence)
  T+120s: auth-api-01     log            CERTIFICATE_EXPIRY_WARNING (trace: maintenance_auth_001) [must be EXCLUDED]
  ```
  Also emit: raw ingress metric for `api-gateway-01` staying **stable** at all times (conflicting DoS evidence).

- [x] **P3-06**: Implement the simulator engine service and handlers for the API routes below (blueprint §10.2). P3 owns emitter lifecycle/state and the deterministic reset hook; P1 owns the cross-domain `ResetService`, lock, DB clearing, and final reset route wiring:
  - `POST /api/v1/simulator/start`
  - `POST /api/v1/simulator/stop`
  - `POST /api/v1/simulator/reset`
  - `POST /api/v1/simulator/scenarios/{scenario_id}/trigger`
  - `GET /api/v1/simulator/status` — returns virtual clock, scenario state, per-source counters

### Phase 2 — Ingestion & Normalization (Hours 3–8)

- [x] **P3-07**: Create `backend/app/ingestion/adapters/` — one adapter module per source, each implementing:
  ```python
  class SourceAdapter(Protocol):
      source_name: str
      def adapt(self, raw: dict) -> CanonicalEvent: ...
  ```
  - `PrometheusAdapter` — maps §9.1.2 Prometheus fields to `CanonicalEvent`
  - `SyslogAdapter` — maps host→entity_id, code+level→event_type+severity via `detector_rules.yaml`
  - `AlertmanagerAdapter` — maps `fingerprint`→source_record_id, `startsAt`→timestamp, normalizes severity
  - `ConfigAuditAdapter` — preserves change details, records the context-only intent in `raw_payload`, and redacts sensitive fields; the detector later sets `AnomalyRecord.context_only=True`
  - All adapters map envelope `scenario_id` to `trace_or_session_id`; the auth-warning fixture deliberately uses `maintenance_auth_001`
  - Canonical source severity mapping is frozen: metric=`0.0`, config=`0.0`, alerts use the alert-severity catalogue, logs use the log-level/template catalogue
  - Simulator inputs add `SIMULATED` and provenance; non-simulator inputs do not

- [x] **P3-08**: Create `backend/app/ingestion/pipeline.py` — shared validation pipeline (blueprint §9.2):
  1. Receive raw event from adapter
  2. Validate modality-specific fields (metric requires `signal_name/value/unit`)
  3. Normalize timestamp → UTC
  4. Redact `raw_payload`: keys matching `password|passwd|token|secret|api_key|authorization` → `[REDACTED]` + add `RAW_PAYLOAD_REDACTED` to `quality_flags`
  5. Reject payload > `EVENT_MAX_PAYLOAD_BYTES` → quarantine
  6. Compute duplicate fingerprint: `SHA-256(entity_id | modality | event_type | normalized-signal | time-bucket)`
  7. Collapse duplicates (modality-specific rules §9.3 — **never collapse metric samples**; collapse identical alerts; collapse declared-repeatable log templates only)
  8. Quarantine invalid events (store in `quarantined_events` with validation reasons)
  9. Persist accepted representative event
  10. Emit accepted event to detection

- [x] **P3-09**: Implement ingestion endpoints:
  - `POST /api/v1/events` → `201` new, `200` idempotent/collapsed, `202` quarantined
  - `POST /api/v1/events/batch` → max 100 items, ordered results, partial success allowed; at most one analysis recompute after whole batch
  - `GET /api/v1/events?limit=&cursor=&modality=&entity_id=` — cursor: `(timestamp DESC, id DESC)` base64url-encoded
  - `GET /api/v1/events/{event_id}` — raw-record drill-down
  - `GET /api/v1/quarantine` — view quarantined records

- [x] **P3-10**: Write `backend/tests/contract/test_adapters.py` — per adapter (blueprint §25.1):
  - Asserts resulting canonical field values (not just "validation succeeded")
  - Tests quarantine reason codes for every invalid fixture
  - Tests alarm-storm collapse increments count and preserves first/last timestamps
  - Tests metric samples are never collapsed
  - Tests exact `source_record_id` retry is idempotent
  - Replays the raw reference bundle through all four adapters and matches `golden_events.jsonl` byte-for-byte after canonical ordering
  - Proves expected/ground-truth files are not accepted as runtime input

### Phase 3 — Anomaly Detection (Hours 6–10)

- [x] **P3-11**: Create `backend/app/detection/detector.py` — `Detector` protocol from blueprint §11.1:
  ```python
  class Detector(Protocol):
      detector_id: str
      def evaluate(self, event: CanonicalEvent, context: DetectionContext) -> list[AnomalyRecord]: ...
  ```

- [x] **P3-12**: Implement `RollingZscoreDetector` (blueprint §11.2, §11.3):
  - Rolling window: `DETECTOR_WINDOW_SECONDS` (300s)
  - Requires `DETECTOR_MIN_BASELINE_POINTS` (20) before firing
  - Z-score threshold: `METRIC_ZSCORE_THRESHOLD` (3.0)
  - Score formula: `0.6 * clamp(abs(z)/5, 0, 1) + 0.4 * clamp(observed/safety_threshold, 0, 1)`
  - Round final score half-up to 2 decimal places
  - Emit anomaly when score ≥ `ANOMALY_THRESHOLD` (0.75)
  - Zero-variance baselines use static threshold only
  - Use `pandas` DataFrame with `rolling().mean()` + `rolling().std()` for efficiency

- [x] **P3-13**: Implement `LogRuleDetector` — maps `event_type` + log level → anomaly type and score via `detector_rules.yaml`. Known patterns: `UPSTREAM_CONNECTION_TIMEOUT`, `UPSTREAM_TIMEOUT`, `CONN_REFUSED`, fatal/error patterns.

- [x] **P3-14**: Implement `AlertSeverityDetector` — normalized alert severity → anomaly score (pass-through). Collapsed duplicate alerts do not create duplicate anomalies.

- [x] **P3-15**: Implement `ConfigChangeMarker` — always sets `context_only=True`, `can_open_incident=False`. Records a config event occurred; never opens incidents or becomes a root cause on its own.

- [x] **P3-16**: Create `backend/tests/fixtures/golden_anomalies.json` — freeze the exact source-event→detector-output manifest, including detector ID, window, score, `context_only`, and `can_open_incident`. The golden scenario has nine actionable anomaly records before the normal DB metric and auth warning; document the config-change marker separately as a non-opening context signal so nobody adds a second gateway alert merely to reach a count. This is the handoff artifact for Person 4.

- [x] **P3-17**: Write `backend/tests/unit/test_detection.py`:
  - Z-score threshold firing and minimum baseline requirement
  - Score formula producing `0.91` for the golden example: `z=4.25`, `baseline=2400`, `observed=7800`, `threshold=5000`
  - Context-only config marker cannot open incident (`can_open_incident=False`)
  - Metric samples are never collapsed; exact source-record-id retry is idempotent

---

## 🟢 Person 4 — Analysis Engine / Topology / RCA (WS2B + WS3)

> **Key libraries:** `networkx`, `numpy`, `pandas`, `pyyaml`, `pytest`

> **Start fixture-first.** Publish the static topology and expected-analysis handoff from the frozen blueprint table in Hour 0–1. Then implement against P3's static anomaly fixture; do not wait for runtime ingestion/detection.

### Phase 0 — Topology Engine First (Hours 0–3, no dependencies)

- [x] **P4-00**: Publish initial handoffs before runtime code: a complete valid `topology.json`, `hypotheses.yaml`, `symptom_families.yaml`, and `backend/tests/fixtures/golden_expected_analysis.json` copied from the frozen factor table as structured data. Include schema/content versions and a checksum. P5 and P2 may mock against these immediately; later runtime generation must reproduce them without diff.
  - Topology must contain all five locked nodes, the traffic path `gateway → checkout → payment → DB`, the `gateway → auth` branch, and parallel `depends_on` edges wherever operational dependency is asserted.

- [x] **P4-01**: Create `backend/app/topology/graph.py` — `nx.MultiDiGraph` built from `fixtures/topology.json`:
  ```python
  # All operations MUST specify relation_type and direction — no generic "connected" boolean
  def get_neighbors(entity_id, relation_type, direction, max_hops) -> list[str]
  def get_path(source, target, relation_type, direction="forward") -> list[str]
  def get_dependency_path(affected_entity, suspected_dependency) -> list[str]
  def get_dependency_blast_radius(root_entity, max_hops) -> list[str]
  def get_traffic_impact_path(source, target) -> list[str]
  def get_traffic_blast_radius(source, max_hops) -> list[str]
  def topology_distance(source, target, relation_type, direction) -> int
  ```
  Traversal policy (blueprint §13.2):
  - "Which dependency could cause failure?" → `depends_on`, forward from affected service
  - "Who is impacted by failed dependency?" → `depends_on`, reverse from suspected dependency
  - "Where does excessive traffic propagate?" → `sends_traffic_to`, forward from change point
  - "What sends traffic into an overloaded entity?" → `sends_traffic_to`, reverse from overloaded entity

- [x] **P4-02**: Create `backend/app/api/topology.py` — API endpoints (blueprint §18.3):
  - `GET /api/v1/topology?incident_id=` — returns nodes with state, typed edges with state
  - `GET /api/v1/topology/path?source=&target=&relation_type=&direction=`
  - `GET /api/v1/topology/blast-radius/{entity_id}?mode=dependency|traffic`

- [x] **P4-03**: Write `backend/tests/unit/test_topology.py`:
  - `get_dependency_blast_radius("payment-db-01")` traverses reverse `depends_on` and returns `payment-api-01`, `checkout-api-01`, then `api-gateway-01` when those dependency edges are present
  - `get_traffic_blast_radius("api-gateway-01", max_hops=3)` returns `checkout-api-01`, `payment-api-01`, `payment-db-01`, and `auth-api-01`; a `max_hops=2` test excludes the DB
  - `get_dependency_path("checkout-api-01", "payment-db-01")` returns correct typed path
  - `topology_distance("api-gateway-01", "payment-db-01", "sends_traffic_to", "forward")` = 3
  - The fixture contains all five locked entities; every edge endpoint resolves; no example edge points at an omitted node
  - Self-edges and unsupported relation types raise errors

### Phase 1 — Incident Manager (Hours 3–7, uses Person 3's `golden_anomalies.json`)

- [x] **P4-04**: Create `backend/app/incidents/manager.py` — incident opening and event attachment (blueprint §12):

  **Incident creation rules (§12.1):**
  - Create new incident when anomaly: exceeds `INCIDENT_OPEN_THRESHOLD`, cannot attach to existing open incident, has valid primary entity, has `can_open_incident=True`
  - On open: run lookback query over preceding `INCIDENT_LOOKBACK_SECONDS` and apply attachment rules (this attaches the T+0 config change to an incident opened by the T+30 metric spike)
  - `started_at` = earliest attached relevant event (not the opening event's timestamp)

  **Attachment scoring (§12.3) — explicit point system:**
  ```
  same entity                    +0.40
  one applicable typed hop       +0.30
  two applicable typed hops      +0.15
  shared trace/session ID        +0.40
  compatible symptom family      +0.20
  event within 60s of first      +0.10
  incompatible symptom family    -0.25
  explicit different trace/session -0.20
  after incident window          ineligible
  ```
  Attach when score ≥ `INCIDENT_ATTACHMENT_THRESHOLD` (0.40) AND at least one identity/topology/trace relationship exists. Persist attached records in `incident_events`; persist every considered record in `incident_event_evaluations` with `decision`, score, and all reason codes. An excluded event must never appear as an attached `incident_event`.

  **Auth warning exclusion (§10.3):** `auth-api-01` log at T+120 with `trace_id=maintenance_auth_001` must score ≤ 0 and be excluded. This is verified via `symptom_families.yaml` (`maintenance_warning` incompatible with `traffic_saturation`) + different trace. Do NOT hard-code this exclusion; it must follow the observable rule.

- [x] **P4-05**: Implement incident lifecycle transitions (blueprint §12.4):
  - `open → investigating` on first successful analysis publication
  - `investigating → resolved` on human Confirm
  - `investigating → rejected` only when every hypothesis in the current run is rejected

- [x] **P4-06**: Create `backend/tests/fixtures/golden_incident_bundle.json` — frozen incident with all attached event IDs plus separate evaluated/excluded event records, each carrying `attachment_score` and `attachment_reasons`. Publish a static version first; after implementation, regenerate and require no diff. This is the handoff artifact for Person 5.

- [x] **P4-07**: Write `backend/tests/unit/test_incident_manager.py`:
  - Config-change marker (T+0) attaches via lookback when symptom (T+30) opens the incident
  - Auth warning (T+120) is excluded — score < 0.40 or no valid identity/topology/trace relationship
  - Incident `started_at` = T+0 (config change time), not T+30 (opening anomaly time)
  - Context-only changes cannot open an incident
  - Stable raw-ingress metric attaches as conflicting evidence (not excluded)

### Phase 2 — Candidate Generator & Root-Cause Ranker (Hours 6–12)

- [x] **P4-08**: Own `fixtures/hypotheses.yaml` and `fixtures/symptom_families.yaml`, then create `backend/app/rca/candidate_generator.py` — generates only catalogue-backed candidates (blueprint §14.1, §14.2):
  - Reads `hypotheses.yaml` catalogue
  - For the golden scenario, generates exactly three candidates:
    1. `configuration_regression`
    2. `dos_or_traffic_surge`
    3. `database_connection_exhaustion`
  - Generation uses: anomaly type, entity types, topology location, recent changes, log patterns
  - Must NOT use an LLM to invent candidate types

- [x] **P4-09**: Create `backend/app/rca/ranker.py` — deterministic weighted scoring (blueprint §14.3, §14.4):

  **Weights (exact, sum to 100%):**
  ```
  Symptom compatibility      25%
  Topology relevance         20%
  Direct logs and alerts     15%
  Propagation consistency    15%
  Metric anomaly evidence    10%
  Change-specific causal fit 10%
  Temporal proximity          3%
  Historical similarity       2%
  ```

  **Factor rubrics (blueprint §14.4 — deterministic only, no LLM):**
  - **Symptom compatibility**: required symptoms observed / required symptoms declared
  - **Topology relevance**: same entity=1.0, one hop=0.8, two hops=0.5, beyond=0.0 (use candidate's traversal policy)
  - **Direct logs and alerts**: both log+alert direct on candidate=1.0, either=0.6, neither=0.0
  - **Propagation consistency**: observed ordered stages / declared expected stages
  - **Metric anomaly**: max applicable anomaly score on candidate or declared impact path
  - **Change-specific causal fit**: 4 checks at 0.25 each (§14.5)
  - **Temporal proximity**: ≤60s=1.0, ≤180s=0.7, ≤300s=0.4, later or after symptom=0.0
  - **Historical similarity**: exact fingerprint=1.0, half features + same cause=0.5, else=0.0

  **Scoring formula:**
  ```
  evidence_score = 100 * sum(weight_i * factor_i)
  ```
  Round final score **half-up to one decimal place** (never truncate). Store unrounded factor inputs. The UI label is **"Evidence score"** — never "confidence score" or "causal probability".

- [x] **P4-10**: Implement **conflict effects** from `hypotheses.yaml` (blueprint §14.4):
  - Each conflict pattern declares `factor`, `operation: subtract|cap`, `value`
  - Apply in catalogue order; clamp factor to `[0.0, 1.0]`
  - Every conflict effect creates a `conflicting` `EvidenceItem` with the pattern ID as `reason_code`
  - For DoS, stable raw ingress/source distribution means one of two required symptoms is present, so `symptom_compatibility=0.5`; `change_causal_fit=0.0` and `temporal_proximity=0.0` already follow the frozen rubric. Emit a conflict item without applying a second, invented penalty.
  - Example: normal DB utilization at T+100 creates conflicting evidence against DB-exhaustion candidate

- [x] **P4-11**: Verify frozen golden outputs (blueprint §10.3 table):
  ```
  Gateway config regression: score 92.1  (rank 1)
  External DoS/traffic surge: score 65.6  (rank 2)
  Payment DB exhaustion:      score 41.5  (rank 3)
  ```

- [x] **P4-12**: Implement a pure deterministic `AnalysisEngine.analyse(incident_bundle) -> AnalysisResult`:
  - Returns candidates, unrounded factors, ranks, conflict reason codes, topology states, and evidence requirements without opening its own DB transaction
  - Same ordered canonical input always produces the same output
  - Does not set `current_analysis_run_id`, supersede runs, or publish partial rows; P1's orchestrator owns fingerprinting and atomic publication
  - Raises typed, sanitized domain errors that P1 can persist as a failed run

- [x] **P4-13**: Add a generator/verification test for `golden_expected_analysis.json`: the implemented engine must reproduce the Hour-0 fixture exactly (factor inputs + scores + reason codes). This remains P4's handoff artifact for Person 5 and Person 2.

- [x] **P4-14**: Write `backend/tests/unit/test_ranker.py`:
  - Golden scenario produces scores `92.1`, `65.6`, `41.5` in that rank order
  - Decimal half-up rounding: verify `92.10` displays as `92.1`
  - DoS candidate: stable raw ingress yields `symptom_compatibility=0.5`, `change_causal_fit=0.0`, `temporal_proximity=0.0`, and a matching conflict EvidenceItem
  - Conflict pattern against DB candidate: normal utilization emits conflicting EvidenceItem with correct `reason_code`
  - Missing factors score zero (not renormalized)

- [x] **P4-15**: Write `backend/tests/integration/test_full_rca_pipeline.py`:
  - Feed golden anomaly bundle → 3 candidates generated
  - Top hypothesis = `configuration_regression` on `api-gateway-01`
  - Score = `92.1` exactly
  - Repeated pure computation yields byte-equivalent `AnalysisResult`
  - With P1's orchestrator test harness: repeated fingerprint is a no-op and a failed computation leaves the prior run current (P1 reviews/owns the transaction assertions)

---

## 🔵 Person 5 — Evidence / Playbooks / Explanation / Review / Audit (WS4)

> **Key libraries:** `pydantic>=2,<3`, `jinja2` (deterministic template rendering), optional `ollama` client behind a feature flag, `httpx`, `pytest`

> **Start immediately on the Playbook engine and response contract.** Consume P4's Hour-0 static expected-analysis fixture; swap to generated output only after the producer test is green. Publish the mock investigation response early so P2 is never blocked by runtime work.

### Phase 0 — Playbook Catalogue (Hours 0–2, fully independent)

- [x] **P5-01**: Create `backend/app/playbooks/engine.py` — lookup service against `fixtures/playbooks.yaml`:
  ```python
  def get_recommendations(hypothesis_type: str, entity_type: str) -> list[PlaybookRecommendation]:
      # Returns only whitelisted catalogue-backed steps
      # Never executes anything
  ```
  Each step from the YAML must have: `step_id`, `title`, `step_type (diagnostic|remediation)`, `applicable_hypothesis_types`, `applicable_entity_types`, `preconditions`, `instructions`, `risk_level`, `rollback_note`, `requires_human_approval: true`

- [x] **P5-02**: Populate `fixtures/playbooks.yaml` with steps covering the golden scenario:
  - `inspect-config-diff` — diagnostic: compare current vs prior rate-limit config
  - `compare-pre-post-metrics` — diagnostic: chart forwarded RPS before/after change
  - `propose-config-rollback` — remediation: re-enable rate limiter (risk_level: low, requires_human_approval: true)
  - Add steps for `dos_or_traffic_surge` and `database_connection_exhaustion` candidates too

- [x] **P5-03**: Write `backend/tests/unit/test_playbook.py`:
  - Every hypothesis type in `hypotheses.yaml` has at least one matching playbook step
  - No playbook step sets `requires_human_approval: false`
  - Unknown hypothesis type returns empty list, not an error

### Phase 1 — Evidence Collector (Hours 1–6, uses `golden_expected_analysis.json`)

- [x] **P5-04**: Create `backend/app/evidence/collector.py` (blueprint §15); `backend/app/rca/` remains P4-owned:
  ```python
  def collect_evidence(
      hypothesis: Hypothesis,
      incident_events: list[CanonicalEvent],
      catalogue_entry: dict,     # from hypotheses.yaml
      quarantined_events: list,  # for missing-evidence generation
  ) -> list[EvidenceItem]:
  ```
  **Four evidence categories (blueprint §15.1):**
  - `observed` — direct fact from an accepted record ("Gateway request rate reached 7,800 requests/s")
  - `correlated` — relevant association, not proof ("Gateway change occurred 30 seconds earlier")
  - `conflicting` — weakens or contradicts ("Packet loss started before the change") — generated from conflict pattern effects in ranker
  - `missing` — specific evidence needed, generated from `expected_evidence` keys in catalogue

  **Missing evidence (§15.2):** Compare available incident records against `expected_evidence` in the catalogue. `expected` = number of unique `expected_evidence` keys. `available` = number satisfied by at least one accepted incident event. Produce exactly one `missing` EvidenceItem per unsatisfied key using the catalogue's collection-request template. `source_event_id` is `NULL` if and only if `kind='missing'`.

  **Evidence coverage:** `available / expected` — extra records do not increase coverage above expected.

- [x] **P5-05**: Fill the feature implementation in P1's `backend/app/api/incidents.py` router skeleton (blueprint §18.2). P1 owns the router/OpenAPI shell; P5 owns investigation aggregation, evidence/recommendation/explanation reads, review, and audit behavior. Coordinate list/summary queries with P4's incident repository rather than duplicating incident logic:
  - `GET /api/v1/incidents` — list with filters + cursor pagination
  - `GET /api/v1/incidents/{id}` — summary
  - **`GET /api/v1/incidents/{id}/investigation`** — the frontend's canonical page contract (§18.2 envelope)
    - Reads `current_analysis_run_id` once; queries entire snapshot against that ID
    - Never assembles from "latest" rows independently
    - Returns: incident, timeline, topology, hypotheses, evidence_by_hypothesis, recommendations_by_hypothesis, explanation, reviews
    - Every hypothesis/evidence/recommendation/explanation carries the envelope's `analysis_run_id`
  - `GET /api/v1/incidents/{id}/timeline` — ordered events with `attachment_score` + `attachment_reasons` per event + per-hypothesis relevance reason codes
    - Attached events come from `incident_events`; evaluated exclusions may be shown as explicitly excluded timeline records from `incident_event_evaluations`, but never as incident evidence
  - `GET /api/v1/incidents/{id}/hypotheses`, `/evidence`, `/recommendations`, `/explanation`
  - `POST /api/v1/incidents/{id}/recompute`
  - `GET /api/v1/incidents/{id}/audit`

- [x] **P5-06**: Create `backend/tests/fixtures/golden_investigation_response.json` immediately from P1's contract examples plus P3/P4 static fixtures. Validate that every run-scoped nested object has the envelope's `analysis_run_id`, every referenced ID resolves, topology is complete, and excluded auth data is labelled excluded rather than evidence. **This is the handoff artifact for Person 2.** Later runtime serialization must reproduce its shape without contract drift.

- [x] **P5-07**: Write `backend/tests/unit/test_evidence_collector.py`:
  - Golden scenario: `configuration_regression` hypothesis has ≥2 `observed` items, ≥1 `correlated`, ≥1 `conflicting`, ≥1 `missing`
  - `waf_decision_logs` expected evidence key is unsatisfied → produces exactly one missing EvidenceItem with catalogue collection-request template
  - `conflicting` items produced by ranker conflict patterns agree with the evidence score reduction (same `reason_code`)
  - `missing` EvidenceItems have `source_event_id=None`

### Phase 2 — Deterministic Explanation (Hours 5–9)

- [x] **P5-08**: Create `backend/app/explanation/template_engine.py` — Jinja2-based deterministic explanation (blueprint §17.1, ALWAYS available):
  - Takes `Hypothesis` + `EvidenceItem` list + playbook recommendations
  - Produces valid `ExplanationOutput` matching blueprint §17.3 contract
  - Wording rule: always "probable root cause" in summary — never "confirmed" (reserved for human review only)
  - No internet required

- [x] **P5-09**: If and only if Milestone 4 is already green, create `backend/app/explanation/llm_engine.py` — optional LLM path behind `EXPLANATION_MODE=llm`; it is not required for P0: ✅ **DONE** — local Ollama provider is schema-constrained, structured-input-only, validator-gated, and safely falls back to the deterministic template
  - Uses `ollama` client against `localhost:11434` — offline
  - Prompt includes ONLY structured Hypothesis + Evidence + Playbook bundle — never raw logs
  - Instructs LLM to return JSON matching §17.3 contract exactly
  - LLM may NOT change scores, ranks, or create evidence

- [x] **P5-10**: Create `backend/app/explanation/validator.py` — backend validation (blueprint §17.4):
  ```python
  def validate_explanation(output: dict, run: AnalysisRun, ...) -> ExplanationOutput | None:
      # 1. JSON matches §17.3 schema
      # 2. analysis_run_id matches the run being explained and is still current
      # 3. Every evidence_id exists and belongs to same incident/hypothesis
      # 4. Every claim has at least one evidence_id
      # 5. Every playbook step_id is whitelisted and applicable
      # 6. No field allows LLM to override deterministic scores or ranks
      # Return None if unrecoverable → caller writes template fallback
  ```

- [x] **P5-11**: Create `backend/app/explanation/service.py` — orchestrator (blueprint §17.1):
  1. Always generate the template explanation first and return its rows to P1's atomic publisher; this service does not commit its own analysis transaction
  2. If `EXPLANATION_MODE=llm`: attempt LLM generation → validate → retry once → else keep template
  3. If stale `analysis_run_id` when optional LLM result arrives, discard it
  4. In normal `template` mode, using the template is not a fallback. Write `EXPLANATION_FALLBACK_USED` only when LLM mode was attempted and the result failed, was invalid, or became stale
  5. Explanation rows are appended, not replaced

- [x] **P5-12**: Write `backend/tests/unit/test_explanation.py`:
  - Template explanation always produces valid output even if all optional fields are absent
  - LLM output with fabricated evidence_id → claim flagged; entire output falls back to template
  - LLM output with wrong `analysis_run_id` → discarded
  - Retry once on LLM failure, then template
  - Every claim in template output has at least one evidence_id

### Phase 3 — Human Review & Audit (Hours 8–13)

- [x] **P5-13**: Create `backend/app/reviews/service.py` — review handler (blueprint §20.1, §18.4):
  - `POST /api/v1/incidents/{id}/review` accepts `{analysis_run_id, decision, hypothesis_id, client_action_id, requested_evidence_id?, reviewer, comment}` and returns `{request_id, generated_at, review}`
  - `client_action_id` is unique per incident; duplicate submission → return existing record (idempotent)
  - `decision=evidence_requested` requires `requested_evidence_id` referencing a `missing` EvidenceItem in the current run
  - `decision=confirmed|rejected` is terminal for that hypothesis in that run; second conflicting terminal → `409 REVIEW_CONFLICT`
  - All decisions on closed incidents → `409 INCIDENT_CLOSED`
  - Decision against hypothesis outside current analysis run → `409 STALE_ANALYSIS` (include current run ID in response)
  - On Confirm: trigger `incident.status → resolved`, set `confirmed_hypothesis_id`

- [x] **P5-14**: Create `backend/app/audit/service.py` — append-only audit trail (blueprint §20.3):
  - Write audit entries for ALL frozen action codes:
    ```
    EVENT_QUARANTINED, EVENT_COLLAPSED, ANOMALY_DETECTED, INCIDENT_OPENED,
    EVENT_ATTACHED, EVENT_EXCLUDED, ANALYSIS_PUBLISHED, PIPELINE_STAGE_FAILED,
    EXPLANATION_FALLBACK_USED, REVIEW_CONFIRMED, REVIEW_REJECTED,
    REVIEW_EVIDENCE_REQUESTED, INCIDENT_STATUS_CHANGED, DEMO_RESET
    ```
  - `EVENT_EXCLUDED` required for golden-scenario auth warning and any other records evaluated but not attached (§20.3)
  - Audit payloads: IDs, reason codes, previous/new state, `request_id`, analysis revision — never secrets or full raw payloads
  - No update or delete API

- [x] **P5-15**: Write `backend/tests/integration/test_review_audit.py`:
  - Confirm hypothesis → `REVIEW_CONFIRMED` audit entry + incident status → resolved
  - Reject all hypotheses → incident status → rejected
  - Duplicate `client_action_id` → returns existing review record, no duplicate audit
  - Stale run review → `409 STALE_ANALYSIS` with current run ID
  - `evidence_requested` on a non-missing evidence item → validation error
  - Auth warning exclusion produces `EVENT_EXCLUDED` audit entry

---

## 🏁 Integration Milestones (Person 1 signs off each gate)

### Milestone 0 — Contract Freeze (~Hour 2)
**Exit gate:** Both apps boot from `bootstrap.sh`; `health` + `ready` respond; every shared artifact has one owner; all static handoffs validate; frontend types regenerate without diff; golden score `92.1` is calculated from frozen factor inputs. Runtime implementations may still be incomplete.

- [x] Person 1: API stubs return example payloads ✅ **DONE** — 25/25 tests pass, milestone validator green
- [ ] Person 2: Route/test-ID manifest committed; investigation shell renders P5's mock response
- [x] Person 3: Raw scenario/provenance bundle and source fixtures frozen; initial golden events/anomalies validate ✅ **DONE** — `golden_events.jsonl`, `golden_anomalies.json`, all scenario input JSONLs, `provenance.json` committed and validated
- [x] Person 4: Full topology + static expected analysis committed; invalid edges fail fast; typed traversal smoke test passes ✅ **DONE** — `topology.json`, `hypotheses.yaml`, `symptom_families.yaml`, `golden_expected_analysis.json` committed and validated
- [x] Person 5: Playbook catalogue and mock investigation response validate; template explanation produces valid output ✅ **DONE** — `playbooks.yaml`, `golden_investigation_response.json` committed; template engine verified

### Milestone 1 — Event Pipeline (~Hour 6)
**Exit gate:** Per-source health and counters visible; baseline running; quarantine and collapse demonstrated; `golden_anomalies.json` produced and consumer tests pass.

### Milestone 2 — Detection & Incident (~Hour 10)
**Exit gate:** Golden scenario trigger opens one incident; config change attaches via lookback; auth warning excluded with audit entry; timeline endpoint returns ordered events.

### Milestone 3 — RCA & Evidence (~Hour 14)
**Exit gate:** Three catalogue candidates generated; frozen scores `92.1 / 65.6 / 41.5`; four evidence categories; conflicting evidence for DoS and DB candidates; immutable analysis run atomically published.

### Milestone 4 — Operator Experience (~Hour 18)
**Exit gate:** Full P0 golden path end-to-end — investigation page, raw record drill-down, playbooks, human review, audit trail, deterministic explanation. No LLM required.

### Milestone 5 — Hardening (~Hour 22)
**Exit gate:** `make verify` green twice after raw-bundle reset/replay. Playwright golden-path test passes. Offline demo confirmed. Primary fallback is deterministic replay of the raw input bundle. Catastrophic UI-only fallback may show a clearly labelled, read-only cached investigation snapshot; it must never be inserted into the live database or presented as a live run.

### Merge and handoff order

| Order | Producer → consumer | Handoff acceptance check |
|---:|---|---|
| 1 | P1 → all | Contracts/OpenAPI load; fixed IDs and error examples pass consumer smoke tests |
| 2 | P3 → P4/P5 | Raw streams replay through adapters; golden canonical/anomaly fixtures validate and hashes match |
| 3 | P4 → P5/P2 | Topology is referentially valid; expected analysis scores are exactly `92.1 / 65.6 / 41.5` |
| 4 | P5 → P2 | Investigation response has one run ID, resolvable references, four evidence kinds, and no excluded event used as evidence |
| 5 | P2/P3/P4/P5 → P1 | Unit/contract tests green; P1 wires end-to-end orchestration and CI without changing feature contracts |

If a producer is late, consumers continue with the last schema-valid static fixture. They do not recreate the producer's file under another name.

---

## 📋 Mandatory CI Gates (blueprint §23.6)

Every PR to `main` must pass ALL of these from a clean checkout:

- [x] `bootstrap.sh` succeeds from locked deps; no undeclared local packages
- [x] Fresh DB upgrades through all migrations; `/api/v1/ready` passes after fixture loading
- [x] Backend unit + contract + integration + catalogue-validation + golden-score tests pass
- [ ] OpenAPI + generated frontend types regenerated; no uncommitted diff ← **P2 scope**
- [ ] Frontend type-check + component tests + production build pass ← **P2 scope**
- [x] Golden fixtures validate: stable IDs, timestamps, analysis-run consistency, ranking, topology direction
- [x] Scenario bundle validates: source/profile hashes, licences/provenance, deterministic rebuild, and raw-to-canonical replay
- [x] Static guard proves runtime packages cannot reference `expected`, `ground_truth`, or test golden-output files
- [x] Offline/template explanation path + simulator reset smoke test pass
- [x] Secret scanning: no API tokens, datasets, databases, build output, or oversized payloads

---

## ⚠️ Golden Rules That Must Not Be Broken

1. **Blueprint §1.3 owns all contract changes.** No teammate edits `contracts/`, DB models, shared fixtures, or API response shapes unilaterally.
2. **Evidence score ≠ causal probability.** The label is always **"Evidence score"** — never "confidence" or "causal probability".
3. **"Confirmed root cause" is used only after a human clicks Confirm.** Pre-review: "Probable root cause". Evidence: "Verified observed fact", "Correlated signals", "Conflicting evidence", "Missing evidence".
4. **LLM never creates incidents, changes scores, ranks, or invents evidence.** It narrates only — and only via the validated structured contract.
5. **Template explanation must always work offline.** LLM narration is optional priority-P1 scope behind a feature flag; it is never a blocker.
6. **Never collapse metric samples.** Only duplicate alerts (identical labels/state) and declared-repeatable log templates are collapsible.
7. **Config changes cannot open incidents or score as root causes alone.** They are always `context_only=True`, `can_open_incident=False`.
8. **Never hard-code the auth-warning exclusion.** It must follow observable symptom-family and trace-ID rules.
9. **Priority-1 scope starts only after Milestone 4 is green.** Priority-2 ideas are documented only; do not confuse the scope label “P1” with Person 1.
10. **Reference datasets are not required at runtime.** The live demo runs entirely from the simulator. Do not commit dataset files to the application repo.
11. **Runtime never reads expected outcomes.** `expected/ground_truth.json` and golden analysis files are test or mock inputs only; ingestion, detection, incident, RCA, evidence, playbook, and explanation packages cannot import them.
12. **One investigation snapshot means one run.** The frontend and API never assemble a page by combining independently fetched “latest” analysis rows.
13. **Excluded is not attached.** Exclusions are persisted/audited as evaluations and may be displayed as excluded context, but they never become incident evidence.

---

## 📦 Repository Structure (target — blueprint §6)

```
network-anomaly-rca/
├── README.md
├── .env.example
├── NETWORK_ANOMALY_RCA_PROTOTYPE_BLUEPRINT.md
├── tasks.md
├── Makefile
├── docs/api-decisions.md, demo-script.md
├── backend/
│   ├── pyproject.toml + requirements.lock
│   ├── alembic.ini + migrations/
│   ├── app/
│       ├── main.py                      ← P1
│       ├── config.py                    ← P1
│       ├── contracts/                   ← P1 (FROZEN)
│       ├── db/models.py + repositories/ ← P1 (FROZEN)
│       ├── orchestration/               ← P1
│       ├── api/                          ← P1 shells; domain owners fill handlers
│       ├── ingestion/adapters/          ← P3
│       ├── simulator/engine.py, emitters/ ← P3
│       ├── detection/                   ← P3
│       ├── incidents/                   ← P4
│       ├── topology/                    ← P4
│       ├── rca/                         ← P4
│       ├── evidence/                    ← P5
│       ├── playbooks/                   ← P5
│       ├── explanation/                 ← P5
│       ├── reviews/                     ← P5
│       ├── audit/                       ← P5
│       └── fixtures/
│           ├── topology.json            ← P4
│           ├── hypotheses.yaml          ← P4
│           ├── symptom_families.yaml    ← P4
│           ├── detector_rules.yaml      ← P3
│           ├── playbooks.yaml           ← P5
│           ├── reference_profiles/      ← P3
│           │   ├── network_profile.json
│           │   └── log_templates.yaml
│           └── scenarios/gateway_rate_limit/ ← P3
│               ├── inputs/{metrics,logs,alerts,config_changes}.jsonl
│               ├── provenance.json
│               └── expected/ground_truth.json  ← tests only
│   └── tests/
│       ├── contract/                    ← P1 + artifact owners
│       ├── unit/                        ← P3, P4, P5
│       ├── integration/                 ← P1, P4, P5
│       └── fixtures/
│           ├── golden_events.jsonl      ← P3 (handoff to P4, P5)
│           ├── golden_anomalies.json    ← P3 (handoff to P4)
│           ├── golden_incident_bundle.json ← P4 (handoff to P5)
│           ├── golden_expected_analysis.json ← P4 (handoff to P2, P5)
│           ├── golden_investigation_response.json ← P5 (handoff to P2)
│           └── source_adapters/         ← P3
├── frontend/
│   └── src/
│       ├── api/                         ← P2
│       ├── contracts/                   ← P2 (generated from OpenAPI)
│       ├── pages/ + components/ + features/ ← P2
│       └── test-fixtures/testid-manifest.ts ← P2
└── scripts/
    ├── bootstrap.sh + dev.sh            ← P1
    ├── seed_demo.py                     ← P1
    ├── build_network_profile.py         ← P3
    └── verify_demo.py                   ← P1
```
