# Person 1 (Team Lead) Change Log

This file tracks all modifications, additions, and validation gates performed by **Person 1 (Team Lead)** during the coding session starting on July 14, 2026.

---

## 🛠️ Summary of Actions

### 1. Database & Persistence Layer (P1-06)
- **Created** `backend/app/db/repositories/event_repository.py`
  - Added `EventRepository` and `QuarantineRepository` functionality for querying and persisting CanonicalEvents, QuarantinedEvents, and CollapsedEventGroups.
- **Created** `backend/app/db/repositories/anomaly_repository.py`
  - Added `AnomalyRepository` for persisting and listing anomaly records within specific sliding windows.
- **Created** `backend/app/db/repositories/incident_repository.py`
  - Added `IncidentRepository` and `AnalysisRunRepository`.
  - Enforced atomic transaction publication boundary and the single active `current` AnalysisRun per incident constraint.
- **Created** `backend/app/db/repositories/hypothesis_repository.py`
  - Added `HypothesisRepository` and `EvidenceRepository` for managing immutable hypotheses and evidence.
- **Created** `backend/app/db/repositories/review_repository.py`
  - Added `ReviewRepository` supporting client action idempotency.
- **Created** `backend/app/db/repositories/audit_repository.py`
  - Added `AuditRepository` with validation for the 14 frozen audit action codes defined in the blueprint.
- **Updated** `backend/app/db/repositories/__init__.py`
  - Exported all repository classes so they can be consumed by other feature modules.

### 2. Orchestration Module (P1-13)
- **Created** `backend/app/orchestration/orchestrator.py`
  - Implemented the central `AnalysisOrchestrator` containing the global serialized in-process analysis lock.
  - Implemented SHA-256 fingerprinting based on sorted event IDs, canonical event content hashes (calculated deterministically from event ID, timestamp, entity, modality, severity, signal metrics, trace ID, and raw payload), topology version, and catalogue versions for idempotency checks.
  - Implemented atomic analysis publication: inserts child tables (hypotheses, evidence, recommendations, explanations) first, marks the previous run superseded, and updates the incident pointer in a single transaction.
- **Updated** `backend/app/orchestration/__init__.py`
  - Registered and exported the central `orchestrator` singleton.

### 3. Reset Service & Simulator API (P1-22)
- **Created** `backend/app/orchestration/reset_service.py`
  - Implemented `ResetService` to perform a clean, FK-safe purge of all demo-generated tables (retaining static topology nodes, edges, and historical incidents).
  - Handles reload of topology edges/entities from `topology.json` and seeds the deterministic historical rate-limiting incident.
  - Exposes `SimulatorResetHook` protocol for Person 3's simulator engine to hook into.
- **Updated** `backend/app/api/simulator.py`
  - Replaced the stub for `POST /simulator/reset` with real execution of `reset_service.execute()`.

### 4. Application Lifespan & Readiness
- **Updated** `backend/app/main.py`
  - Added a FastAPI lifespan context manager (`lifespan`) to automatically reload topology nodes/edges and seed the historical incident on first startup if the database is empty.
- **Updated** `backend/app/readiness.py`
  - Modified the status check of the `"orchestrator"` component from a static string to query `orchestrator.status()`, ensuring `/api/v1/ready` reflects registration status of adapters.

### 5. Build, Lint Guard, and Testing (P1-23)
- **Created** `backend/tests/unit/test_orchestrator.py`
  - Implemented 13 unit tests verifying lock presence, algorithm versioning, fingerprint determinism, mock component registrations, and repository audit validation.
- **Updated** `backend/tests/contract/test_ground_truth_firewall.py`
  - Expanded scan lists to ensure **all** runtime modules (including reviews, audit, orchestration, and simulator) are checked for import/open access references to forbidden test directories (like `/expected/` or `golden_*` files).
- **Updated** `Makefile`
  - Added target `validate-fixtures` (runs pytest on contract tests).
  - Added target `guard` (runs the ground-truth firewall test).
  - Configured `verify` CI gate target to run `validate-fixtures`, `test`, and `build`.

---

## 🛠️ Phase 1 Integration Gating (Milestones 2, 3, 4, 5) Actions
- **Created** `backend/app/orchestration/publisher.py`:
  - Implemented `OrchestrationPublisher` to route newly ingested canonical events directly through `AnalysisOrchestrator.process_event()`.
- **Updated** `backend/app/ingestion/pipeline.py`:
  - Set default publisher to `OrchestrationPublisher` to wire ingestion directly into the orchestrator pipeline.
- **Updated** `backend/app/detection/service.py`:
  - Exposed `DetectorService` implementing `DetectorProtocol` for the orchestrator.
- **Created** `backend/app/incidents/manager.py`:
  - Implemented lookback query, typed topology hop checks, shared trace/session correlation, and symptom family compatibility rules.
  - Handled SQLite timezone naivety issues cleanly for datetime comparisons.
- **Created** `backend/app/rca/engine.py`:
  - Implemented deterministic `AnalysisEngine` generating hypotheses, evidence items, playbook recommendations, and template explanations for the gateway rate-limit scenario.
- **Created** `backend/tests/unit/test_incident_manager.py`:
  - Added unit tests for IncidentManager checking lookback configuration change attachment and auth warning exclusion.
- **Updated** `backend/app/contracts/__init__.py`:
  - Imported and exported `ExplanationClaim`.
- **Created/Updated** `backend/app/api/incidents.py`:
  - Implemented `/incidents`, `/timeline`, `/hypotheses`, `/evidence`, `/recommendations`, `/explanation`, `/audit`, `/recompute`, `/review`, `/investigation` endpoints querying database models and repositories.

---

## 🔬 Phase 2/3 Compatibility Scan & Verification Actions

We performed a methodical compatibility check of Person 1 and 3 tasks and resolved the following integration issues:

1. **Standardized HTTPExceptions:**
   - Modified endpoints `/review` and `/recompute` to raise standard FastAPI `HTTPException` with explicit `detail` dictionary objects rather than raw JSONResponses.
2. **Review Validation Rules:**
   - Enforced stale analysis detection checking that `req.analysis_run_id` matches `incident.current_analysis_run_id`.
   - Added validation check to reject evidence request decisions if the requested evidence item is not found or is not of kind `"missing"` (raising a 422 error).
3. **Enum Alignment & Incident Resolution:**
   - Standardized review decision comparisons to use `ReviewDecision` enum values (`"confirmed"`/`"rejected"`/`"evidence_requested"` instead of `"confirm"`/`"reject"`/`"request_evidence"`), allowing incident status to resolve properly.
4. **Timeline Relevance Mapping:**
   - Populated `hypothesis_relevance` in the timeline dynamically using evidence reason codes in `/investigation`.
5. **Cursor-based Pagination:**
   - Replaced offset pagination with full cursor-based encoding and decoding in `/incidents`.
6. **Audit Scope Scanning:**
   - Updated `/audit` to fetch both parent incident audit records and child action audit records by parsing JSON payload dictionaries.
7. **Pydantic Validation Alignment:**
   - Removed `failure_reason` argument from `AnalysisRun` contract parsing and joined playbook step list instructions to string format.
8. **Topology DB Connection:**
   - Reverted `/topology` parameter dependency overrides to keep it independent, ensuring unit tests' mock-patching remains compatible.

---

## 🚦 Verification Results

All local and integration validation gates are green:
1. **Total Test Suite:** `pytest` - **Passed** (All **91/91** unit, contract, and integration tests passed cleanly in the `.venv` context).
2. **Incident Manager Unit Tests:** `pytest tests/unit/test_incident_manager.py` - **Passed**.
3. **Simulator Phase 1 Tests:** `pytest tests/test_simulator_phase1.py` - **Passed**.

---

## 📋 tasks.md Checklist Updated
- Marked **P1-16** to **P1-19** (Milestones 2, 3, 4, and 5) as completed (`[x]`).

---

## 🔗 Concise Layer Integration Map

How each layer connects end-to-end, from dataset reference to the frontend:

```
data/ (reference-only, offline)
  ↓ informed signal names, ranges, log templates, attack vocab
scripts/build_scenario_bundle.py
  ↓ generates deterministic JSONL fixture files
fixtures/scenarios/gateway_rate_limit/inputs/
  ├── metrics.jsonl       (Prometheus-format — NSL-KDD/UNSW-NB15 ranges)
  ├── logs.jsonl          (Syslog-format — Loghub templates)
  ├── alerts.jsonl        (Alertmanager-format)
  └── config_changes.jsonl (Config audit — GAIA run.zip format)
  ↓
SimulatorEngine (app/simulator/engine.py)
  Reads JSONL timeline groups → emits via PersistentIngestionSink
  ↓
PersistentIngestionSink (app/simulator/ingestion.py)
  Calls IngestionPipeline.ingest(source, raw) per record
  ↓
IngestionPipeline (app/ingestion/pipeline.py)
  Routes raw dict → matching SourceAdapter via ADAPTERS[source]
  Validates, deduplicates, collapses repeatable events
  Persists accepted CanonicalEvent → events table
  Calls AcceptedEventPublisher.publish(event)
  ↓
OrchestrationPublisher (app/orchestration/publisher.py)
  Calls AnalysisOrchestrator.process_event(event, session)
  ↓
AnalysisOrchestrator (app/orchestration/orchestrator.py)
  Acquires in-process analysis lock
  Runs: DetectorService → IncidentManager → AnalysisEngine atomically
  SHA-256 fingerprint for idempotency
  Atomic publication: marks prior run superseded, switches incident pointer
  ↓
API Layer (app/api/incidents.py)
  GET /incidents           → cursor-paginated list
  GET /investigation       → full snapshot (hypotheses, evidence, timeline)
  POST /review             → ReviewDecision transitions + AuditLog entries
  GET /audit               → per-incident action trail
  ↓
Frontend (polling @ 1500ms)
  Consumes /incidents + /investigation + /topology endpoints
```

### Adapter–Source Mapping

| Source string | Adapter | Key raw fields | Output |
|---|---|---|---|
| `simulator.prometheus` | `PrometheusAdapter` | `sample_id`, `metric`, `value`, `labels.entity_id` | `signal_name/value`, `entity_id`, `event_type` |
| `simulator.syslog` | `SyslogAdapter` | `record_id`, `host`, `code`, `level`, `trace_id` | `event_type`, `severity` from LEVEL_SEVERITY map |
| `simulator.alertmanager` | `AlertmanagerAdapter` | `fingerprint`, `startsAt`, `labels.entity_id/severity` | `severity=0.95` for critical, alert dedup |
| `simulator.config_audit` | `ConfigAuditAdapter` | `change_id`, `changed_at`, `target_entity_id` | `CONFIG_VALUE_CHANGED`, `severity=0.0`, `context_only=True` |

---

## 📦 Dataset Ingestion Capability Research

### Finding: Datasets Are Reference-Only at Runtime

Per `DatasetDescription.md` and blueprint §3.3: **"None are loaded at runtime. The live demo runs entirely from the deterministic simulator scenario bundle."**

The ingestion pipeline is architecturally capable of reading real dataset records but the current wiring uses only the simulator as the emitter.

### What the Adapters CAN Handle

| Adapter | Dataset equivalent | Mapping feasibility |
|---|---|---|
| `PrometheusAdapter` | NSL-KDD / UNSW-NB15 | ✅ Columns (`count`, `src_bytes`, `dst_host_count`) map directly to `signal_name/value` via derivation rules in `DatasetDescription.md §1` |
| `SyslogAdapter` | Loghub HDFS / BGL | ✅ Each log line can be parsed into `record_id`, `host`, `code`, `level` using template matching |
| `AlertmanagerAdapter` | NSL-KDD `neptune`/UNSW `DoS` attack rows | ✅ Attack records map to alert payloads via `attack_cat → alertname` |
| `ConfigAuditAdapter` | GAIA `run.zip` injection records | ✅ `service + anomaly_type + start_time` maps directly to `change_id`, `changed_at`, `target_entity_id` |

### Gap: No Live Dataset Reader

There is no `DatasetReader` class or batch-ingest script reading raw CSVs/ARFFs/log files into the `ADAPTERS` pipeline. The `build_scenario_bundle.py` script generates fixed JSONL fixtures offline.

To enable live dataset ingestion the following would be needed:
1. `MetricDatasetReader` — reads `data/nsl_kdd/KDDTrain+.txt`, applies synthetic column derivation rules, emits Prometheus-format dicts.
2. `LogDatasetReader` — parses `HDFS.log`/`BGL.log` raw lines into SyslogAdapter-compatible dicts.
3. `GaiaRunReader` — parses `run.zip` injection records into ConfigAuditAdapter-compatible dicts.
4. A CLI script or `POST /api/v1/ingest/batch` endpoint wiring these readers to `IngestionPipeline`.

### Verdict

The ingestion pipeline **is capable** of handling real dataset records as long as they are shaped correctly. The four adapters cover all dataset modalities. Only the offline → online data reader bridge is missing. Adding dataset readers would be a self-contained extension with no contract changes required.

