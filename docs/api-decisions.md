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

## M0-009 — Expanded reference dataset and leakage firewall

- **Status:** accepted for dataset integration
- **Decision:** NSL-KDD, UNSW-NB15, Loghub HDFS/BGL, GAIA MicroSS, and the
  sample distributed-trace dataset remain reference-only. They may produce
  attributed profiles, templates, mapping proposals, and offline evaluation
  samples, but the live incident remains the deterministic simulator scenario.
- **Forbidden transformations:** dataset class/anomaly labels may not derive
  runtime severity, alerts, hypotheses, incident membership, RCA factors, or
  signal values; time buckets may not manufacture trace IDs; approximate
  network formulas may not be named as measured operational metrics; GAIA
  identities may not replace the frozen topology without a full contract change.
- **Reason:** these restrictions prevent target leakage, false time-based
  correlation, misleading measurement semantics, and fixture incompatibility.
- **Affected owners:** all; Persons 3 and 4 resolve dataset/source and
  topology/RCA semantics respectively.
