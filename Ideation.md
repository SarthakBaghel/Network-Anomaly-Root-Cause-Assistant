```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ DATA SOURCES  [MVP: simulator only]                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Telemetry Simulator                                                       │
│   - metrics, logs, config changes                                           │
│   - (fault-injected, gives you ground truth for free)                       │
│                                                                             │
│ [FUTURE: real Prometheus/OTel, syslog/SNMP, real telco feeds]               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ INGESTION & NORMALIZATION  [MVP]                                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Simulator                                                                 │
│   - one ingestion function (not full REST/adapter framework — just a        │
│     Python function per event type, calling the same validator)             │
│                                                                             │
│ • Schema validation → CanonicalEvent, exactly:                              │
│   {event_id, timestamp, entity_id, modality,                                │
│    event_type, severity, raw_payload}                                       │
│                                                                             │
│ • Invalid/incomplete records                                                │
│   - quarantined, not dropped                                                │
│   - (this alone still gives you the "missing evidence" story)               │
│                                                                             │
│ • UTC timestamp normalization                                               │
│                                                                             │
│ • Duplicate/alarm-storm collapsing                                          │
│                                                                             │
│ [FUTURE: WebSocket streaming, multi-format adapters — REST polling          │
│  every 1-2s is enough for the demo; judges won't check the transport]       │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ STORAGE  [MVP: one SQLite DB, not five stores]                              │
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
│ ANALYSIS ENGINE  [MVP: simple, deterministic detectors]                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Anomaly Detector:                                                         │
│   metrics  → rolling Z-score + static threshold                             │
│   logs     → error-code mapping (known bad codes → anomaly)                 │
│   alerts   → severity rule                                                  │
│   changes  → recent-change flag (config/deploy in window = signal)          │
│   [FUTURE: Isolation Forest, log-template drift]                            │
│                                                                             │
│ • Incident Manager                                                          │
│   - groups anomalies into one incident window                               │
│                                                                             │
│ • Topology Engine                                                           │
│   - static, hand-authored dependency graph                                  │
│   - frozen convention: source → target means "source depends on target"     │
│   - e.g. checkout-service → database                                        │
│   - downstream blast radius = traverse graph in REVERSE from the failing    │
│     node                                                                    │
│   - [FUTURE: automated topology discovery]                                  │
│                                                                             │
│ • Correlation Engine                                                        │
│   - candidate ELIGIBLE if:                                                  │
│     ✓ topologically connected (graph edge exists)                           │
│     ✓ temporally plausible (cause precedes symptom)                         │
│     ✓ supported by ≥1 metric/log/change event                               │
│   (historical co-occurrence is NOT a required filter anymore —              │
│    a novel failure with no matching history must still be findable)         │
│                                                                             │
│ • Root-Cause Ranker                                                         │
│   - weighted score, not a strict filter:                                    │
│                                                                             │
│     Temporal relevance           20%                                        │
│     Topology relevance           20%                                        │
│     Change/deployment evidence   20%                                        │
│     Metric anomaly severity      15%                                        │
│     Supporting logs              15%                                        │
│     Propagation consistency      10%                                        │
│     + optional historical-similarity bonus, up to +10%                      │
│                                                                             │
│   → tiers: Confirmed evidence / Correlated signal / Missing evidence        │
│                                                                             │
│ • Playbook Engine                                                           │
│   - suggests from a small predefined list of                                │
│     safe remediation steps; never auto-executes                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ LLM EXPLANATION LAYER  [MVP, this is your differentiator]                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Narrates only — never computes the root cause                             │
│                                                                             │
│ • Every claim must cite an evidence_id                                      │
│                                                                             │
│ • Unsupported claim → regenerate, OR fall back to a                         │
│   deterministic templated sentence if regeneration still                    │
│   fails (this fallback is cheap insurance — never let the                   │
│   demo show a blank or an unciteable claim on stage)                        │
│                                                                             │
│ • Wording rule: before human confirmation, always say                       │
│   "Probable root cause" / "High-confidence evidence" —                      │
│   reserve "Confirmed root cause" for AFTER operator accepts it              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ DASHBOARD  [MVP]                                                            │
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
│ HUMAN REVIEW  [MVP]                                                         │
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
│ INCIDENT MEMORY  [MVP: minimal, not learning]                               │
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
