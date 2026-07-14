# Network Anomaly Root-Cause Assistant — Design Document

## 0. Problem Statement (reference)

> Build a Network Anomaly Root-Cause Assistant that ingests telemetry, logs, alerts,
> topology data, and configuration changes to detect anomalies and generate explainable
> root-cause hypotheses. The solution must distinguish correlation from likely causation,
> rank probable causes, and provide supporting evidence.

Requirements (1-8) and where each is satisfied in this design:

| # | Requirement | Satisfied by |
|---|---|---|
| 1 | Ingest telemetry, logs, alerts, topology, config changes from multiple sources | §3.1 Ingestion Layer |
| 2 | Detect anomalies across relevant time windows | §3.3 Anomaly Detector, Incident Manager |
| 3 | Correlate while avoiding simple time-based blame | §3.3 Correlation Engine (topology + temporal + evidence, not time-proximity alone) |
| 4 | Use topology/dependency data for impact paths | §3.3 Topology Engine |
| 5 | Ranked root-cause hypotheses with supporting evidence | §3.3 Root-Cause Ranker + Evidence Collector |
| 6 | Separate confirmed evidence / correlated signals / missing evidence | §3.3 Evidence Collector, §5 Wording Rules |
| 7 | Generate incident timeline (what happened, when) | §3.5 Incident Timeline View |
| 8 | Recommend next diagnostic/remediation steps, maintain auditable trail | §3.3 Playbook Engine, §3.6 Audit Trail |

This document describes the **two-day MVP build**. Every feature is tagged `[MVP]` or
`[FUTURE]`. Only `[MVP]` items should be attempted during the hackathon; `[FUTURE]` items
are shown on the architecture diagram for vision but explicitly labeled as not implemented,
per the feasibility review already incorporated into this design.

---

## 1. Tech Stack Summary (Python-first)

| Layer | Primary choice | Why |
|---|---|---|
| Backend framework | **FastAPI** | async, auto-generates OpenAPI docs, plays well with Pydantic |
| Schema/validation | **Pydantic v2** | single source of truth for CanonicalEvent, EvidenceBundle; also validates LLM JSON output |
| Database | **SQLite** via **SQLModel** | SQLModel = SQLAlchemy + Pydantic in one model, avoids duplicating schema definitions between DB layer and API layer; zero setup/ops overhead |
| Numerical analysis | **NumPy**, **Pandas** | rolling Z-score on metric time series |
| Graph / topology | **NetworkX** | dependency graph, forward/reverse traversal for blast radius, shortest-path distance for scoring |
| Local LLM | **Ollama** (serving Qwen, already set up locally) via `ollama` Python client or raw `requests` to `localhost:11434` | already running on your RTX 5070 Ti setup, no API cost, works offline for the demo |
| LLM output validation | Pydantic model + manual re-ask-on-failure loop | enforces Correction 6 (structured JSON, programmatic citation check) |
| Frontend | **React** (Vite) + **Recharts** (timeline/charts) + **react-force-graph** or **vis-network** (topology visualization) | strongest visual impact for judges; topology graph is your single best demo asset |
| Frontend fallback | **Streamlit** (pure Python) | faster to build if the team is backend-heavy and short on frontend hours — trade-off: weaker topology graph interactivity, but zero JS needed. Decide as a team in hour 1, don't switch mid-build. |
| HTTP between frontend/backend | REST polling every 1-2s (`fetch`/`axios` or Streamlit's own rerun loop) | WebSocket is `[FUTURE]` — not worth the complexity for a 2-day build |
| Testing | **pytest** | one smoke test per module: fixture in, schema-valid output out |
| Config | **python-dotenv** | LLM endpoint, DB path, thresholds |

Install (backend):
```bash
pip install fastapi uvicorn pydantic sqlmodel networkx pandas numpy ollama pytest python-dotenv --break-system-packages
```

---

## 2. Canonical Schemas

These are frozen at hour 0 and never edited except by the designated schema owner (Person 1).

### 2.1 CanonicalEvent (all ingested data normalizes to this)
```python
class CanonicalEvent(SQLModel, table=True):
    event_id: str            # unique, e.g. "evt-101"
    timestamp: datetime      # UTC, always
    entity_id: str           # topology node this event belongs to, e.g. "checkout-service"
    modality: str            # "metric" | "log" | "alert" | "config"
    event_type: str          # e.g. "DB_CONNECTION_TIMEOUT", "HIGH_CHECKOUT_ERROR_RATE"
    severity: float          # 0.0 - 1.0, normalized
    raw_payload: str         # JSON-encoded original payload, preserved as-is
    quarantined: bool = False  # True if it failed validation but wasn't discarded
```

### 2.2 Incident
```python
class Incident(SQLModel, table=True):
    incident_id: str
    start_time: datetime
    end_time: datetime | None
    affected_entities: str   # JSON list of entity_ids
    status: str              # "open" | "reviewed"
```

### 2.3 Hypothesis (Root-Cause Ranker output)
```python
class Hypothesis(SQLModel, table=True):
    hypothesis_id: str
    incident_id: str
    candidate_entity: str
    confidence_score: float  # 0.0 - 1.0, LABELED "confidence score", never "causal probability"
```

### 2.4 Evidence (Evidence Collector output — separate table, per Correction 1)
```python
class Evidence(SQLModel, table=True):
    evidence_id: str
    hypothesis_id: str
    source_event_id: str     # foreign key to CanonicalEvent
    tier: str                # "observed" | "correlated" | "missing"  (per Correction 2 wording)
    description: str
```

### 2.5 LLM structured output contract (Correction 6)
```json
{
  "summary": "string",
  "claims": [
    {"text": "string", "evidence_ids": ["evidence-14"]}
  ],
  "remediation": [
    {"text": "string", "playbook_step_id": "db-exhaustion-immediate-01"}
  ]
}
```
Backend validates every `evidence_id` and `playbook_step_id` actually exists before
displaying the claim. On failure: retry generation once, then fall back to a
deterministic template (never show an unvalidated or blank claim live).

---

## 3. Layer-by-Layer Design

### 3.1 Data Sources / Telemetry Simulator `[MVP]`
**Library:** stdlib `random`, `datetime`; optional `Faker` for realistic entity names.

Key features:
- Emits all four modalities so the multimodal story is genuinely true, not partial:
  - `metric` — time-series values (latency, error rate, connection count) per entity
  - `log` — text/error-code events per entity
  - `alert` — generated when a metric crosses a threshold (Correction 3), e.g.
    `{"event_type": "HIGH_CHECKOUT_ERROR_RATE", "modality": "alert", "severity": 0.95}`
  - `config` — simulated config/deployment change events with timestamp + actor
- **Fault injection mode**: deliberately triggers a root cause (e.g. database connection
  pool exhaustion) that cascades to 2-3 downstream services — this is your **ground truth**
  for the evaluation metrics later, and your main demo script.
- Emits at least one deliberately malformed event, to prove the quarantine path works live.

### 3.2 Ingestion & Normalization `[MVP]`
**Libraries:** FastAPI (optional thin API), Pydantic v2, stdlib `datetime`/`zoneinfo`, `hashlib`.

Key features:
- One ingestion function per modality, all converging on the same Pydantic validator.
- **UTC normalization** at the point of ingestion — non-negotiable, applied before
  anything else touches the event.
- **Duplicate/alarm-storm collapsing**: fingerprint (entity_id + event_type + rounded
  timestamp) to collapse repeated alarms into one logical event.
- **Quarantine, don't drop**: any record failing validation is stored with
  `quarantined=True` rather than discarded — this directly produces the "missing evidence"
  signal downstream (a quarantined event means a gap in what could be collected).
- REST polling (`GET /events/latest`) for the frontend — WebSocket is `[FUTURE]`.

### 3.3 Storage `[MVP]`
**Library:** SQLModel over a single SQLite file.

Tables: `canonical_event`, `incident`, `hypothesis`, `evidence`, `audit_log`.
No separate raw/metrics/topology/audit databases — one file, `raw_payload` as a JSON
column. The full multi-store diagram is still shown on the architecture slide as the
platform vision; the implementation is one file.

### 3.4 Analysis Engine `[MVP]`

**Anomaly Detector** — Library: NumPy/Pandas
- `metric` → rolling Z-score + static threshold
- `log` → error-code-to-severity mapping (dict lookup, not ML)
- `alert` → severity rule (pass-through, since simulator already tags severity)
- `config`/`deploy` → recent-change flag: any config/deploy event in the incident window
  is itself treated as an anomaly signal
- `[FUTURE]`: Isolation Forest, log-template drift detection

**Incident Manager** — explicit grouping rule (Correction 5), implemented as a plain
Python filter, no library needed:
```
Attach event E to incident I if ALL of:
  1. E.timestamp is within the configured time window of I (e.g. 5 minutes)
  2. E.entity_id is within N topology hops of any entity already in I (e.g. max 2 hops)
  3. E.modality/event_type is relevant to I's anomaly category
```
This prevents an unrelated notification-service warning from being swept into a
database incident merely because it happened at a similar time — directly answers the
problem statement's "avoid simple time-based blame" requirement.

**Topology Engine** — Library: NetworkX
- Dependency graph built once at startup from a small hand-authored JSON/YAML file
  (`topology.yaml`): nodes = entities, edges = dependencies.
- **Frozen convention**: `source → target` means "source depends on target"
  (e.g. `checkout-service → database`).
- Blast radius = reverse traversal (`nx.ancestors` in the dependency direction) from the
  failing node outward to find downstream-affected services.
- `[FUTURE]`: automated topology discovery from live traffic.

**Correlation Engine** — plain Python, no library needed. Candidate is **eligible**
(not filtered out) if ALL of:
```
1. topologically connected — a dependency path exists to the affected entity
2. temporally plausible  — candidate's anomaly precedes the symptom in time
3. supported by ≥1 metric/log/config event (not topology alone)
```
Historical co-occurrence is **not** a required filter (this was corrected from the
original design — a novel failure with no matching history must still be findable).

**Root-Cause Ranker** — plain Python weighted score, output labeled **"confidence
score"**, never "causal probability":
```
Temporal relevance           18%
Topology relevance           18%
Change/deployment evidence   18%
Metric anomaly severity      14%
Supporting logs              14%
Propagation consistency      10%
Historical similarity         8%   (0 if no match found; never blocks eligibility)
                             ----
                             100%
```
This is now a **separate step from Evidence Collector** (Correction 1) — the ranker
only answers "how likely is this candidate?"

**Evidence Collector** — separate component, answers "what records support or weaken
this candidate?" Attaches exact `CanonicalEvent` records per hypothesis, tiered as
(Correction 2 wording — never "confirmed" pre-review):
- **Observed evidence** — factual, directly-recorded signals (e.g. "DB connections
  reached 100%")
- **Correlated signals** — temporally/statistically associated, no proven causal path
- **Missing evidence** — what would raise confidence if it were collected (e.g. a
  quarantined or absent record)

**Playbook Engine** — small predefined list of safe remediation suggestions keyed by
`event_type` (e.g. `db-exhaustion-immediate-01` → "review recent connection-limit
change"). Suggestion only, never auto-executed.

### 3.5 LLM Explanation Layer `[MVP]`
**Library:** `ollama` Python client (local Qwen model) or `requests` against
`localhost:11434`.

Key features:
- Input to the LLM is **only** the structured Hypothesis + Evidence bundle — never raw
  logs, never asked to "figure out" the cause. This is the architectural guarantee that
  the LLM narrates rather than computes causation.
- Output is **structured JSON** per the §2.5 contract, not free text.
- **Programmatic validation** (Correction 6): backend checks every `evidence_id` and
  `playbook_step_id` actually exists. On failure → retry generation once → else fall
  back to a deterministic templated sentence built from the Hypothesis/Evidence objects
  directly (never show a blank or unvalidated claim on stage).
- Wording rule enforced here too: "probable root cause" / "high-confidence evidence"
  before human review; "confirmed" is reserved for post-review UI state only.

### 3.6 Dashboard `[MVP]`
**Libraries:** React + Vite, Recharts, react-force-graph (or vis-network), axios.
(Or Streamlit, if the team chooses the all-Python path — see §1 tradeoff note.)

Views:
- **Incident Timeline** (problem statement requirement 7) — chronological, time-aligned
  view of every event in the incident window (metrics/logs/alerts/config changes),
  showing what happened and when, with the anomaly trigger point marked.
- **Live Topology** — dependency graph with the propagation path highlighted.
- **Ranked probable causes** — Hypothesis list with confidence scores.
- **Evidence Explorer** — the three-tier view (Observed / Correlated / Missing), each
  item clickable back to the raw `CanonicalEvent`.
- **Suggested remediation / next diagnostic steps** (problem statement requirement 8) —
  from the Playbook Engine, plus LLM-generated "investigation steps" for closing
  Missing-evidence gaps.
- **Audit Trail** (problem statement requirement 8) — every detector firing, every
  graph traversal, every threshold crossed, every human decision — pulled directly from
  the `audit_log` table.

### 3.7 Human Review `[MVP, core actions only]`
- Confirm / Reject / Request Evidence — core three actions.
- Modify-weighting and Approve-simulated-remediation are `[FUTURE-if-time-permits]` —
  build only after the core loop works end to end.
- Any Confirm/Reject writes to `audit_log` and updates the Incident's status and
  (if confirmed) the Hypothesis's final human-verified label.

### 3.8 Incident Memory `[MVP, minimal]`
- Store: completed incident, human-confirmed cause, reviewer decision.
- Retrieve: one manually seeded "similar past incident" to demonstrate the concept.
- `[FUTURE]`: automatic co-occurrence weight updates, full similar-incident retrieval,
  model retraining.

---

## 4. Workflow (plain text, end to end)

```
1. Simulator generates a stream of metric, log, alert, and config events, including
   one injected fault (e.g. database connection pool exhaustion) that cascades to
   downstream services, and one deliberately malformed event.

2. Ingestion validates each event against CanonicalEvent. Valid events are UTC-
   normalized, deduplicated, and stored. The malformed event is quarantined, not
   dropped — this becomes a "missing evidence" data point later.

3. Anomaly Detector scans metrics (rolling Z-score), logs (error-code mapping),
   alerts (severity rule), and config changes (recent-change flag) and flags anomaly
   events with a severity score.

4. Incident Manager groups the flagged anomalies into one incident window using the
   explicit rule: within the time window AND within N topology hops AND modality-
   relevant. This is what prevents an unrelated event from being swept in just
   because it happened around the same time.

5. Topology Engine expands from the incident's affected entities outward over the
   dependency graph (using the frozen source-depends-on-target convention) to find
   candidate upstream causes and the downstream blast radius.

6. Correlation Engine filters candidates down to those that are topologically
   connected, temporally plausible (cause precedes symptom), and supported by at
   least one metric/log/config event. Historical similarity is checked but never
   required.

7. Root-Cause Ranker scores each surviving candidate using the weighted formula
   (§3.4) and produces a confidence score — explicitly labeled as a ranking
   heuristic, not a statistical causal probability.

8. Evidence Collector attaches the exact supporting CanonicalEvent records to each
   ranked candidate, tiered into Observed evidence, Correlated signals, and Missing
   evidence.

9. Playbook Engine looks up a suggested remediation/diagnostic step matching the
   top candidate's event_type.

10. LLM Explanation Layer receives ONLY the Hypothesis + Evidence + Playbook bundle
    (never raw logs) and generates a structured JSON summary, per-claim citations,
    and remediation text. The backend validates every evidence_id and
    playbook_step_id before display; unvalidated claims are regenerated or replaced
    with a deterministic template.

11. Dashboard displays: the incident timeline, the topology graph with propagation
    path highlighted, ranked probable causes, the three-tier evidence view, the
    suggested remediation, and the full audit trail — all sourced from the same
    SQLite tables, polled every 1-2 seconds.

12. Human reviewer confirms, rejects, or requests more evidence. Their decision is
    written to the audit log and to the Incident's final status. Only upon Confirm
    does the UI language change from "probable root cause" to "confirmed root
    cause."

13. Incident Memory stores the completed incident and its human-confirmed outcome,
    available for manual similar-incident lookup on future runs.
```

---

## 5. Wording Rules (enforced in exactly one place: Person 1's constants file)

| Situation | Correct term |
|---|---|
| Before human review | "Probable root cause" |
| Evidence directly observed | "Observed evidence" |
| Evidence associated but not causally proven | "Correlated signals" |
| Evidence that would help but wasn't collected | "Missing evidence" |
| Ranker output | "Confidence score" (never "causal probability") |
| After human clicks Confirm | "Confirmed root cause" (only time this word is used) |

---

## 6. What to Say in the Pitch (Actually Implemented vs. Future)

**Actually implemented:**
Synthetic multimodal telemetry ingestion (metrics/logs/alerts/config), canonical
normalization, UTC handling, deduplication, quarantine-not-discard, threshold/Z-score
anomaly detection, explicit incident grouping, static dependency topology with frozen
traversal direction, eligibility-based correlation (not historical-required), weighted
deterministic ranking, separated evidence collection with three tiers, citation-
validated LLM narration with deterministic fallback, incident timeline, suggested
remediation, human review loop, full audit trail.

**Future integration:**
Real Prometheus/OpenTelemetry/syslog/SNMP ingestion, real telecom RAN/core/OSS
feeds, Isolation Forest and log-template drift detection, automated topology
discovery, historical co-occurrence learning and similar-incident retrieval,
controlled (non-simulated) remediation execution.

---

## 7. Team Ownership Reference (see prior discussion for full role breakdown)

- **Person 1 (Lead)**: schemas, fixtures, wording constants, integration checkpoints, scope cuts.
- **Person 2 (UI/Dashboard/Deliverables)**: §3.6, pitch deck, evaluation slide.
- **Person 3 (Ingestion/Storage)**: §3.1, §3.2, §3.3.
- **Person 4 (Analysis/Correlation/Ranking)**: §3.4 — hardest, most differentiating piece, start first.
- **Person 5 (Explainable AI)**: §3.5, citation validation, playbook wiring.
