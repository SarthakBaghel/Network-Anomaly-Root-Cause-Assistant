# API and Contract Decisions

This append-only record follows blueprint §1.3. A decision changes shared
contracts only when its affected owners have reviewed it.

## M0-001 — Golden scenario and scope cut

- **Status:** accepted for Milestone 0
- **Decision:** P0 implements only `gateway_rate_limit_disabled` using scenario
  trace/session ID `scenario_gateway_rate_limit_001`. The optional DoS scenario
  remains priority-P1 work and starts only after Milestone 4 is green.
- **Affected owners:** all

## M0-002 — Runtime versions and dependency mode

- **Status:** accepted for Milestone 0
- **Decision:** Python 3.12+; Node 22 LTS; FastAPI; Pydantic v2; synchronous
  SQLAlchemy 2 with `sqlite:///`; Alembic; React/TypeScript/Vite; Tailwind CSS;
  `@xyflow/react`; Recharts; Vitest; `@playwright/test`.
- **Reason:** the blueprint's SQLite URL is synchronous. Node 22 is the current
  supported LTS line for the selected frontend test stack.
- **Drift recorded:** blueprint §6.1 still mentions Node 20; `.nvmrc` and CI use
  Node 22. A future blueprint revision should synchronize the wording.
- **Affected owners:** Persons 1 and 2

## M0-003 — Frozen IDs

- **Status:** accepted for Milestone 0
- **Scenario ID:** `gateway_rate_limit_disabled`
- **Trace/session ID:** `scenario_gateway_rate_limit_001`
- **Entities:** `api-gateway-01`, `checkout-api-01`, `payment-api-01`,
  `payment-db-01`, `auth-api-01`
- **Incident/run IDs in golden fixtures:** `inc_001`, `run_007`
- **Affected owners:** all fixture producers and consumers

## M0-004 — Golden score and seeded history

- **Status:** accepted for Milestone 0
- **Decision:** seed one historical gateway rate-limit incident in P0 so the
  configuration-regression factor `historical_similarity=0.5` and displayed
  evidence score remains `92.1`.
- **Drift recorded:** blueprint §3.4 classifies seeded historical similarity as
  priority P1, but §§7.5/10.3 freeze it into the P0 golden score. The frozen
  score wins for the demo.
- **Affected owners:** Persons 1 and 4

## M0-005 — Source envelope and canonical severity

- **Status:** accepted for Milestone 0
- **Decision:** every simulator record has a transport envelope containing
  `scenario_id`, `emitted_at`, and `provenance`; adapters map `scenario_id` to
  `trace_or_session_id` unless the raw source supplies an explicit decoy trace.
  Metric and configuration events enter canonical normalization with severity
  `0.0`; alert/log severities come from checked-in catalogues.
- **Affected owners:** Persons 1 and 3

## P3-001 — Deterministic event identity and batch publication

- **Status:** accepted
- **Decision:** canonical event IDs are deterministic ULIDs whose time component
  comes from the source timestamp and whose entropy is derived from
  `SIMULATOR_SEED`, source identity, and source record ID. Batch ingestion
  persists ordered partial-success results first, then invokes one serialized
  batch orchestration pass; RCA publication occurs at most once per affected
  incident after the batch.
- **Affected owners:** Persons 1 and 3

## P3-002 — Event-feed cursors

- **Status:** accepted
- **Decision:** `GET /api/v1/events` returns a generated-at envelope containing
  `items` and `next_cursor`. The opaque base64url cursor freezes the last
  `(timestamp, event_id)` tuple and active modality/entity filters. Malformed or
  filter-mismatched cursors return `400 INVALID_CURSOR`.
- **Affected owners:** Persons 2 and 3

## M0-006 — Nine anomalies and configuration context

- **Status:** accepted for Milestone 0
- **Decision:** `golden_anomalies.json` contains nine actionable detector
  anomalies plus a separate `context_markers` collection for the non-opening
  configuration marker. The marker has `context_only=true` and
  `can_open_incident=false`; it is not included in `IncidentSummary.anomaly_count`.
- **Reason:** this preserves blueprint §10.3's anomaly count while retaining the
  §11.2 configuration context signal explicitly.
- **Affected owners:** Persons 1, 3, and 4

## M0-007 — Attached versus excluded event persistence

- **Status:** accepted for Milestone 0
- **Decision:** `incident_events` stores attached events only. A separate
  `incident_event_evaluations` table stores every considered event with
  `attached|excluded`, score, and reason codes. Excluded records may appear as
  explicitly excluded timeline context but are never evidence.
- **Affected owners:** Persons 1, 4, and 5

## M0-008 — Ground-truth firewall

- **Status:** accepted for Milestone 0
- **Decision:** files below any `expected/` directory, any file named
  `ground_truth.json`, and `backend/tests/fixtures/golden_*` are test/mock data.
  Runtime ingestion, detection, incident, topology/RCA, evidence, playbook, and
  explanation modules may not import or open them.
- **Affected owners:** all backend owners

## M0-009 — Run-scoped explanation publication

- **Status:** accepted for Milestone 0
- **Decision:** Person 1 creates an immutable `AnalysisBuildContext` containing
  the pending analysis-run and incident IDs before invoking the analysis
  engine. Person 5 returns one or more validated `ExplanationDraft` values in
  `AnalysisResult.explanation_rows`; the atomic publisher validates every
  draft against that context, preserves its `template|llm` generator, and
  appends all rows before switching `incident.current_analysis_run_id`.
- **Fallback rule:** normal template generation is not a fallback. An
  `EXPLANATION_FALLBACK_USED` audit record is appended only when the result
  includes an uppercase catalogue-style fallback reason code and positive
  attempt count. Invalid or run-mismatched drafts fail the building run and
  leave the prior run current.
- **Compatibility:** `explanation_payload` remains a deprecated constructor
  input for one transition window and is converted to a validated draft.
- **Affected owners:** Persons 1, 4, and 5

## M0-010 — Pure RCA computation and database-aware adapter

- **Status:** accepted for Milestone 0
- **Decision:** Person 4's engine accepts an immutable
  `IncidentAnalysisBundle` and returns an immutable `RcaComputationResult`.
  Neither contract imports SQLAlchemy, repositories, or ORM models. Person 1's
  `RcaAnalysisAdapter` performs repository reads, binds pending run/incident
  IDs, invokes the Person 5 evidence/playbook/explanation services, and returns
  the existing publisher-facing `AnalysisResult`.
- **Historical matching:** exact fingerprint plus confirmed cause scores `1.0`;
  the same confirmed cause with at least half of the historical row's declared
  features scores `0.5`; otherwise it scores `0.0`. Ordering is deterministic.
- **Metadata persistence:** topology states, conflict reason codes, and evidence
  requirements are immutable publication metadata for API assembly and
  validation. They are not duplicated into new database columns in P0.
- **Conflict evidence:** pure computation emits run-agnostic conflict drafts.
  The adapter creates the run-scoped evidence representation, avoiding a
  pending database-run dependency inside the pure engine.
- **Affected owners:** Persons 1, 4, and 5

## M0-011 — Machine-readable deterministic RCA catalogue

- **Status:** accepted for Milestone 0
- **Decision:** `hypotheses.yaml` version `hypotheses-1.2` contains the
  machine-readable anomaly/event patterns, candidate selectors, metric anomaly
  types, change-fit keys, typed traversal origins, conflict match conditions,
  and deterministic summaries consumed by Person 4. Runtime ranking never
  reads the frozen expected-analysis fixture and never infers values from prose.
- **Golden DoS rule:** the observed forwarded-traffic symptom supplies one of
  two declared symptoms. `STABLE_RAW_INGRESS` caps that factor at `0.5` and
  emits conflict evidence without applying an additional penalty.
- **Golden DB rule:** checkout degradation is the declared typed dependency
  origin, producing `checkout-api-01 -> payment-api-01 -> payment-db-01` and a
  two-hop topology factor of `0.5`. Normal DB utilization caps metric support
  at zero and emits `NORMAL_DB_UTILIZATION` conflict evidence.
- **Affected owners:** Persons 1, 4, and 5

## M0-012 — Run-explicit review mutation envelope

- **Status:** accepted as the Person 5 Phase 3 prerequisite boundary
- **Decision:** `ReviewRequest` retains required `analysis_run_id` even though
  the earlier task shorthand omitted it. This makes the stale-analysis intent
  explicit and keeps the frontend action bound to the rendered snapshot.
  `POST /incidents/{id}/review` returns a mutation envelope containing
  `request_id`, `generated_at`, and the immutable `ReviewRecord`.
- **Idempotency:** the request ID is deterministically derived from incident ID
  and `client_action_id`, so retries return the same response identity and do
  not create another audit record.
- **Affected owners:** Persons 1, 2, and 5

## M0-013 — Validated audit-writer handoff

- **Status:** accepted as the Person 5 Phase 3 prerequisite boundary
- **Decision:** audit producers hand Person 5 a validated `AuditWrite` value
  carrying the frozen action, actor and object identity, request ID, applicable
  incident/run/revision context, reason codes, state transition, and bounded
  metadata. Raw payloads, secrets, authorization material, and stack traces are
  rejected at this boundary.
- **Incident trail query:** event-owned records such as `EVENT_EXCLUDED` remain
  addressed to their event but are retrieved for an incident through their
  sanitized `payload.incident_id` reference.
- **Affected owners:** all backend producers; Persons 1 and 5 own the boundary

## M0-014 — Accepted-event orchestration handoff

- **Status:** accepted for the Person 1 recovery integration
- **Decision:** a newly accepted representative is published exactly once to
  `OrchestrationPublisher` after persistence. Idempotent retries, collapsed
  duplicates, and quarantined records are not republished. The ingestion
  response reports `analysis_state="processed"` after that synchronous handoff.
- **Runtime path:** API ingestion and simulator ingestion both use the shared
  `IngestionPipeline`; feature routes do not invoke detectors, incident logic,
  or RCA modules directly.
- **Affected owners:** Persons 1 and 3
# Person 2 live overview contracts (2026-07-15)

- Simulator mutations and status use the typed `SimulatorStatusResponse` contract. The existing `sources` counter map remains available for simulator-engine consumers; the ordered `source_health` list is the dashboard contract and always includes the four simulator adapters plus `fixture.cmdb_topology`.
- `GET /api/v1/anomalies?limit=20` is a read-only overview endpoint. It returns detector-owned anomaly records with entity identity in a generated-at envelope; the frontend does not derive or synthesize anomalies.
- Mock Service Worker is opt-in through `VITE_ENABLE_MSW=true`, so normal development talks to the configured backend.

## M0-015 — Production pipeline dependency contract

- **Status:** accepted for the P0 production integration
- **Detector registry:** production uses the same four-detector set that owns
  the frozen handoff: rolling Z-score, log rule, alert severity, and the
  non-opening configuration marker. The approved output remains nine
  actionable anomalies plus one context marker. EWMA and topology-cascade
  implementations are retained as later-scope features but are not registered
  in the P0 production pipeline.
- **Timestamp groups:** simulator records sharing a timestamp are persisted as
  one ordered batch. Detection completes for the group before incident
  attachment, and RCA publishes at most once per affected incident. This makes
  same-timestamp stable raw ingress available as attached conflict evidence.
- **Persistence ownership:** Person 3 returns uncommitted anomaly rows; Person
  1 persists and audits them exactly once. Persons 4 and 5 continue returning
  uncommitted analysis output to Person 1's atomic publisher.
- **Affected owners:** Persons 1, 3, and 4

## M0-016 — Durable immutable analysis publication metadata

- **Status:** accepted for the P0 production integration; supersedes the
  no-column metadata clause in M0-010
- **Decision:** every analysis run stores Person 4's topology states, typed
  paths, conflict reason codes, and evidence requirements. Person 5 and API
  assembly read that immutable run snapshot rather than reconstructing it from
  a later topology/catalogue state.
- **Failure durability:** a failed publication rolls back its nested child
  writes and pointer mutations, then durably commits the failed run and
  `PIPELINE_STAGE_FAILED` audit before returning the sanitized failure. The
  prior current run remains current.
- **Reset:** required simulator stop/reset hooks are part of the reset contract;
  hook failure fails the request rather than reporting a partial reset as
  successful.
- **Affected owners:** Persons 1, 3, 4, and 5

## M0-017 — Production-derived UI handoffs

- **Status:** accepted for the P0 production integration
- **Golden generation:** P4/P5 handoff artifacts are captured from an isolated
  reset and raw replay through the production FastAPI application. Volatile
  database IDs and wall-clock timestamps are normalized only after the real
  detector, incident, RCA, evidence, playbook, explanation, review, and audit
  paths have completed.
- **Frontend contract:** `backend/openapi.json` is generated from the production
  FastAPI app and P2's TypeScript declarations are generated from that file.
  Drift checks fail when either generated artifact is stale.
- **Live UI:** the MSW-disabled Playwright configuration starts migrated SQLite,
  FastAPI, and Vite processes and discovers incident, run, hypothesis, evidence,
  review, and audit identities from production responses at runtime.
- **Affected owners:** Persons 1, 2, 4, and 5

## M0-018 — Two-pass final integration release gate

- **Status:** accepted for the P0 release boundary
- **Decision:** `make verify` owns the final release decision and runs two
  complete passes. Each pass includes production artifact reproduction,
  OpenAPI and generated TypeScript drift checks, contract/runtime-firewall
  validation, the focused production pipeline/failure/reset suite, all other
  backend tests, frontend tests/build, and MSW-disabled live Playwright.
- **Reset boundary:** both live passes share one migrated SQLite database. The
  P1 production reset service clears and reseeds that database after pass one,
  before any pass-two check executes.
- **Determinism:** each pass captures a runtime projection that excludes only
  volatile identities and wall-clock fields. The gate compares event order,
  incident semantics, analysis metadata, timeline decisions, hypotheses,
  evidence, recommendations, topology states, explanation, review decision,
  and audit actions byte-for-byte and reports a SHA-256 digest.
- **Affected owners:** Person 1 owns the runner; all persons own their included
  boundary tests.

## EXT-001 — Post-blueprint reference scenario and modality expansion

- **Status:** accepted and implemented on 2026-07-16
- **Scope relationship:** this is an additive implementation extension, not a
  retroactive requirement of `BLUEPRINT.md`. It supersedes the five-entity and
  four-telemetry-adapter scope assumptions in M0-003 and the Person 2 live
  overview note only for the expanded demo catalogue. The primary Milestone-0
  golden scenario and its frozen semantic output remain supported.
- **Scenario scope:** the simulator adds reference-derived network-path
  degradation, DDoS / SYN flood, GAIA resource saturation, port scan /
  reconnaissance, HDFS DataNode failure, and distributed trace anomaly paths.
  Their authoritative mapping is recorded in
  `docs/reference-scenario-extensions.md`.
- **Contract scope:** `trace` is a canonical modality, `simulator.trace` is a
  source-health adapter, `topology-1.2` adds HDFS entities, and simulator
  scenario responses expose reference datasets, transformation version, and a
  quality flag through the generated OpenAPI client.
- **Runtime data policy:** the application replays curated deterministic
  profiles rather than loading large raw datasets during a demo. Runtime
  ingress recursively rejects dataset outcome fields; offline readers isolate
  them under `_meta`, which is stripped before canonical ingestion.
- **RCA and safety:** every scenario must publish its expected top hypothesis
  through the production pipeline with zero quarantined records. Hypotheses
  declare exact catalogue playbook IDs, catalogue cross-validation is
  mandatory, all recommendations require human approval, and no remediation is
  auto-executed.
- **Verification:** the two-pass release gate produced identical semantic
  digest
  `sha256:196ff3c123a4e9ca73a3aa7934f03696b2de7e38539de06295a23ea42fff9419`.
- **Affected owners:** all implementation owners
