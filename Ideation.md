┌──────────────────────────────────────────────────────────┐
│                    DATA SOURCES                          │
│                                                          │
│ Metrics         → time-series KPIs (latency, error rate, │
│                    throughput, resource utilization)      │
│ Logs            → syslog/text, JSON app logs, per-device  │
│                    log formats (RAN/core/OSS each differ)  │
│ Alerts          → threshold-fired alarms, dedup'd events   │
│ Config Changes  → diffs/commits to device or service       │
│                    configuration, with timestamp + actor   │
│ Deployments     → release/rollout events, version bumps    │
│ Service Topology→ dependency graph: which node feeds       │
│                    which (RAN→transport→core→OSS/BSS)      │
│ Historical Incidents → past root-cause resolutions, used   │
│                    later for co-occurrence scoring          │
└──────────────────────────┬───────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│                INGESTION LAYER                            │
│                                                          │
│ FastAPI REST APIs   → per-source-type adapters, one       │
│                        endpoint/parser per raw format      │
│                        (syslog, SNMP/JSON alarm, CSV KPI)  │
│ WebSocket           → streaming path for live metrics/     │
│                        alerts (vs. batch REST for logs)    │
│ Telemetry Simulator → generates synthetic fault-injected   │
│                        traffic for demo + ground-truth eval│
│ Schema Validation   → each adapter maps its raw format to  │
│                        ONE canonical event schema          │
│                        (timestamp, entity_id, modality,    │
│                        severity, raw_payload preserved);   │
│                        failed/incomplete records are NOT   │
│                        dropped — quarantined and logged as │
│                        a data-quality gap (feeds "missing  │
│                        evidence" downstream)                │
│ Timestamping        → normalize all timestamps to UTC at   │
│                        ingestion (different domains log in │
│                        different timezones/formats —       │
│                        silent misalignment breaks temporal-│
│                        precedence logic later)              │
│ Duplicate Detection → collapse repeated alarm storms into  │
│                        one logical event before it reaches │
│                        the analysis layer                   │
└──────────────────────────┬───────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│             RAW AND NORMALIZED STORAGE                    │
│                                                          │
│ Raw Event Store       → original untouched payload per    │
│                          event, keyed by event_id — this   │
│                          is what evidence trace-back reads  │
│                          from later                         │
│ Metrics Store         → normalized time-series, indexed by │
│                          entity_id for windowed queries      │
│ Logs/Alerts/Changes DB→ canonical-schema records, queryable │
│                          by entity, time window, modality    │
│ Topology Store        → the dependency graph itself         │
│                          (nodes = network/service entities,  │
│                          edges = dependency direction)        │
│ Incident and Audit DB → every past hypothesis, its evidence, │
│                          human verdict, and final outcome    │
└──────────────────────────┬───────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│              ANALYSIS AND INTELLIGENCE                     │
│                                                          │
│ Anomaly Detector      → per-modality statistical/ML         │
│                          detection (z-score/Isolation Forest │
│                          on metrics, template-drift on logs,  │
│                          threshold rules on alerts); outputs  │
│                          anomaly events with confidence score │
│ Incident Manager      → groups related anomaly events into   │
│                          one incident window (start/end time, │
│                          affected entities)                    │
│ Topology Engine       → given an incident, expands outward    │
│                          over the dependency graph to find    │
│                          candidate upstream causes and         │
│                          downstream blast radius                │
│ Correlation Engine    → this is the causal-vs-correlation      │
│                          core: a candidate cause is accepted   │
│                          only if (a) a directed dependency edge│
│                          exists cause→symptom, (b) cause        │
│                          precedes symptom in time, (c) historical│
│                          co-occurrence clears a threshold —      │
│                          NOT decided by the LLM                  │
│ Root-Cause Candidate Generator → enumerates every node that     │
│                          passed the correlation engine's filters │
│ Evidence Collector    → for each candidate, gathers the exact    │
│                          supporting records (alert IDs, config   │
│                          diff, KPI drift) with links back to      │
│                          the Raw Event Store                       │
│ Root-Cause Ranker     → scores each candidate: weighted            │
│                          combination of graph distance + temporal  │
│                          precedence strength + historical           │
│                          co-occurrence frequency → produces the     │
│                          Confirmed / Correlated / Missing tiers       │
│ Playbook Engine       → looks up a matching remediation playbook    │
│                          from historical incidents, if one exists    │
│                          (suggestion only, never auto-executed)       │
└──────────────────────────┬───────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│                 EXPLAINABLE AI LAYER                       │
│                                                          │
│ LLM converts structured results into:                     │
│ • Incident summary       → plain-language restatement of   │
│                             the incident window and impact   │
│ • Root-cause explanation → narrates the ranked hypotheses;   │
│                             every claim must cite a specific  │
│                             evidence_id from the Evidence      │
│                             Collector — unciteable claims       │
│                             are rejected and regenerated          │
│ • Investigation steps    → what a human should check next to    │
│                             raise confidence on "Missing"          │
│                             evidence items                          │
│ • Remediation guidance   → maps to the Playbook Engine's           │
│                             suggestion, phrased for a human           │
│                             to review, not act on directly             │
│                                                          │
│ LLM does not calculate the root cause.                     │
│ (all ranking/scoring already happened in the Analysis layer;│
│  the LLM only narrates and cites what was already proven)   │
└──────────────────────────┬───────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│                    USER INTERFACE                          │
│                                                          │
│ Dashboard        → live incident feed, severity, status      │
│ Live Topology    → the dependency graph with the current      │
│                     incident's propagation path highlighted    │
│ Timeline         → time-aligned view of metrics/logs/alerts/    │
│                     config-changes around the incident window    │
│ Root Causes      → ranked hypothesis list with confidence scores  │
│ Evidence         → the three-tier view (Confirmed/Correlated/      │
│                     Missing), each item clickable back to raw data  │
│ Blast Radius     → downstream entities affected, from the           │
│                     Topology Engine's expansion                       │
│ Remediation      → suggested playbook, clearly marked as              │
│                     "suggested," never "executed"                       │
│ Audit Trail      → full run trace: which detector fired, which         │
│                     graph edges were traversed, which thresholds         │
│                     were crossed — this is the traceability layer          │
└──────────────────────────┬───────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│                 HUMAN-IN-THE-LOOP                          │
│                                                          │
│ Confirm                  → operator accepts the top hypothesis  │
│ Reject                   → operator dismisses it; forces re-rank │
│                             or flags a gap in the correlation logic│
│ Modify                   → operator edits the hypothesis/evidence   │
│                             weighting manually                       │
│ Request Evidence         → operator flags a "Missing" evidence item  │
│                             as something to prioritize collecting next│
│ Approve Simulated Remediation → operator approves the playbook for     │
│                             a dry-run/simulated action only — this is    │
│                             the guardrail: nothing executes below a       │
│                             confidence threshold without this step         │
└──────────────────────────┬───────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│              INCIDENT MEMORY AND LEARNING                  │
│                                                          │
│ Final Cause         → the human-confirmed root cause, stored  │
│                        as ground truth for this incident        │
│ Resolution          → what remediation actually resolved it       │
│ Reviewer Feedback    → confirm/reject/modify actions feed back      │
│                        into the Correlation Engine's co-occurrence   │
│                        weighting, so future scoring improves           │
│ Similar Incident Matching → retrieval over the Incident and Audit DB   │
│                        to surface past cases matching current signals   │
│ Audit History        → permanent, queryable record for compliance         │
│                        and post-mortem review                              │
└──────────────────────────────────────────────────────────┘
