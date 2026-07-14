```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ DATA SOURCES [MVP]                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Telemetry Simulator                                                       │
│   - metrics, logs, alerts, config changes                                   │
│   - (alerts added per Correction 3 — simulator emits an alert               │
│      event once a threshold is crossed, e.g.:                              │
│      {event_type: "HIGH_CHECKOUT_ERROR_RATE", modality: "alert",            │
│       severity: 0.95} — cheap to add, makes the multimodal story            │
│      genuinely true rather than partially true)                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ INGESTION & NORMALIZATION [MVP]                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Simulator                                                                 │
│   - one ingestion function (not full REST/adapter framework — just a        │
│     Python function per event type, calling the same validator)             │
│                                                                             │
│ • Schema validation → CanonicalEvent, exactly:                              │
│   {event_id, timestamp, entity_id, modality,                                │
│    event_type, severity, raw_payload}                                       │
│                                                                             │
│ • Invalid/incomplete records → quarantined, not dropped                     │
│   (this alone still gives you the "missing evidence" story)                 │
│                                                                             │
│ • UTC timestamp normalization                                               │
│                                                                             │
│ • Duplicate/alarm-storm collapsing                                          │
│                                                                             │
│ [FUTURE: WebSocket streaming, multi-format adapters — REST polling          │
│ every 1-2s is enough for the demo; judges won't check the transport]        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STORAGE [MVP: one SQLite DB, not five stores]                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Tables:                                                                   │
│   metric_points, events, anomalies, incidents,                              │
│   incident_events, hypotheses, evidence, audit_logs                         │
│                                                                             │
│ • raw_payload stored as a JSON column on `events`                           │
│                                                                             │
│ (diagram can still SHOW separate logical stores for the pitch —             │
│ implementation is one file, one connection, zero ops overhead)              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ANALYSIS ENGINE [MVP]                                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Anomaly Detector:                                                         │
│   metrics  → rolling Z-score + threshold                                    │
│   logs     → error-code mapping                                             │
│   alerts   → severity rule (now consistent — alerts exist                   │
│              in the simulator, per Correction 3)                            │
│   changes  → recent-change flag                                             │
│                                                                             │
│ • Incident Manager — grouping rule now explicit:                            │
│   attach an event to an incident when ALL of:                               │
│     1. it falls within the time window (e.g. 5 minutes)                     │
│     2. its entity is within N topology hops of the affected                 │
│        entity (e.g. max 2 hops)                                             │
│     3. its modality/category is relevant to the incident type               │
│   → this is what stops an unrelated notification-service warning            │
│     from getting swept into a database incident just because                │
│     it happened around the same time                                        │
│                                                                             │
│ • Topology Engine — frozen edge convention (unchanged):                     │
│   source → target means "source depends on target"                          │
│                                                                             │
│ • Candidate Generator                                                       │
│   ↓                                                                         │
│                                                                             │
│ • Root-Cause Ranker                                                         │
│   answers: "how likely is this candidate?"                                  │
│                                                                             │
│   weighted score (Correction 4: weights now correctly sum to 100%,          │
│   history folded IN rather than added on top):                              │
│                                                                             │
│     Temporal relevance          18%                                         │
│     Topology relevance          18%                                         │
│     Change/deployment evidence  18%                                         │
│     Metric anomaly severity     14%                                         │
│     Supporting logs             14%                                         │
│     Propagation consistency     10%                                         │
│     Historical similarity        8% (optional; 0 if no match —              │
│                                  never a hard filter)                       │
│                                                                             │
│   → output labeled "Confidence score" only — NOT "causal probability"       │
│     (an 89% score is a ranking heuristic, not a statistical claim)          │
│                                                                             │
│   ↓                                                                         │
│                                                                             │
│ • Evidence Collector                                                        │
│   answers: "what records support or weaken this candidate?"                 │
│                                                                             │
│   attaches exact events per candidate, divided into                         │
│   (Correction 2 — relabeled, never "confirmed"):                            │
│                                                                             │
│     Observed evidence                                                       │
│       (factual: "DB connections reached 100%")                              │
│                                                                             │
│     Correlated signals                                                      │
│       (temporally/statistically associated, no                              │
│        proven causal path)                                                  │
│                                                                             │
│     Missing evidence                                                        │
│       (would raise confidence if collected)                                 │
│                                                                             │
│   ↓                                                                         │
│                                                                             │
│ • Playbook Engine                                                           │
│   suggests from a small predefined safe-remediation list;                   │
│   never auto-executes                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LLM EXPLANATION LAYER [MVP]                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ • LLM output is now STRUCTURED JSON, not free text                          │
│   (Correction 6 — validate programmatically, not by reading                 │
│   natural language after the fact):                                         │
│                                                                             │
│   {                                                                         │
│     "summary": "...",                                                       │
│     "claims": [                                                             │
│       {"text": "...", "evidence_ids": ["evidence-14"]}                      │
│     ],                                                                      │
│     "remediation": [                                                        │
│       {"text": "...", "playbook_step_id": "db-exhaustion-immediate-01"}     │
│     ]                                                                       │
│   }                                                                         │
│                                                                             │
│ • Backend validation (deterministic code, not the LLM):                     │
│   - does every evidence_id actually exist in the Evidence Collector's       │
│     output?                                                                 │
│   - does every playbook_step_id actually exist in the Playbook Engine?      │
│   - any claim with no evidence_id → unsupported                             │
│   → on failure: retry generation once, else fall back to a                  │
│     deterministic templated sentence (never show a blank or                 │
│     unvalidated claim live)                                                 │
│                                                                             │
│ • Wording rule:                                                             │
│   always "probable root cause" / "high-confidence evidence"                 │
│   before human confirmation                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ DASHBOARD [MVP]                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Charts                                                                    │
│ • live topology (highlight propagation path)                                │
│ • timeline                                                                  │
│ • ranked probable causes                                                    │
│ • evidence tiers (clickable to raw record)                                  │
│ • suggested remediation                                                     │
│ • audit trail                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ HUMAN REVIEW [MVP]                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Confirm                                                                   │
│ • Reject                                                                    │
│ • Request Evidence                                                          │
│                                                                             │
│ (Modify-weighting and Approve-simulated-remediation are                     │
│ nice-to-haves — implement only if time remains after the                    │
│ core loop works end to end)                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ INCIDENT MEMORY [MVP: minimal, not learning]                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Store: completed incident, human-confirmed cause,                         │
│   reviewer decision                                                         │
│                                                                             │
│ • Retrieve: one manually seeded "similar past incident" to                  │
│   demonstrate the concept                                                   │
│                                                                             │
│ [FUTURE: automatic co-occurrence weight updates,                            │
│ full similar-incident retrieval, model retraining]                          │
└─────────────────────────────────────────────────────────────────────────────┘
```
