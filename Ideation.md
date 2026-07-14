
# AI-Powered Root Cause Analysis (RCA) System Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA SOURCES                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Metrics                                                                   │
│   - Time-series KPIs (latency, error rate, throughput, resource utilization)│
│                                                                             │
│ • Logs                                                                      │
│   - Syslog/text logs, JSON application logs, per-device log formats         │
│   - (RAN/Core/OSS each differ)                                              │
│                                                                             │
│ • Alerts                                                                    │
│   - Threshold-fired alarms, deduplicated events                             │
│                                                                             │
│ • Config Changes                                                            │
│   - Configuration diffs/commits with timestamp and actor                    │
│                                                                             │
│ • Deployments                                                               │
│   - Release events, rollout events, version changes                         │
│                                                                             │
│ • Service Topology                                                          │
│   - Dependency graph (RAN → Transport → Core → OSS/BSS)                     │
│                                                                             │
│ • Historical Incidents                                                      │
│   - Previous root-cause resolutions                                         │
│   - Used later for historical co-occurrence scoring                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             INGESTION LAYER                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ • FastAPI REST APIs                                                         │
│   - Source-specific adapters                                                │
│   - Syslog, SNMP, JSON alarms, CSV KPIs, etc.                               │
│                                                                             │
│ • WebSocket                                                                 │
│   - Streaming metrics and alerts                                            │
│                                                                             │
│ • Telemetry Simulator                                                       │
│   - Generates synthetic fault-injected traffic                              │
│                                                                             │
│ • Schema Validation                                                         │
│   - Converts every source into one canonical event schema                   │
│   - Invalid records quarantined (not discarded)                             │
│                                                                             │
│ • Timestamp Normalization                                                   │
│   - Converts all timestamps to UTC                                          │
│                                                                             │
│ • Duplicate Detection                                                       │
│   - Collapses repeated alarm storms                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      RAW & NORMALIZED STORAGE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Raw Event Store                                                           │
│   - Original payloads                                                       │
│                                                                             │
│ • Metrics Store                                                             │
│   - Normalized time-series database                                         │
│                                                                             │
│ • Logs / Alerts / Config DB                                                 │
│   - Canonical event records                                                 │
│                                                                             │
│ • Topology Store                                                            │
│   - Network/service dependency graph                                        │
│                                                                             │
│ • Incident & Audit Database                                                 │
│   - Hypotheses, evidence, human verdicts                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     ANALYSIS & INTELLIGENCE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Anomaly Detector                                                          │
│   - Statistical/ML detection                                                │
│   - Outputs anomaly events with confidence                                  │
│                                                                             │
│ • Incident Manager                                                          │
│   - Groups anomalies into incident windows                                  │
│                                                                             │
│ • Topology Engine                                                           │
│   - Finds upstream causes and downstream blast radius                       │
│                                                                             │
│ • Correlation Engine                                                        │
│   Candidate accepted only if:                                               │
│     ✓ Dependency edge exists                                                │
│     ✓ Cause precedes symptom                                                │
│     ✓ Historical co-occurrence passes threshold                             │
│                                                                             │
│ • Root Cause Candidate Generator                                            │
│                                                                             │
│ • Evidence Collector                                                        │
│   - Alert IDs                                                               │
│   - Config diffs                                                            │
│   - KPI drift                                                               │
│   - Links back to Raw Event Store                                           │
│                                                                             │
│ • Root Cause Ranker                                                         │
│   Score = Graph Distance                                                    │
│         + Temporal Precedence                                               │
│         + Historical Co-occurrence                                          │
│                                                                             │
│   Produces:                                                                 │
│     • Confirmed                                                             │
│     • Correlated                                                            │
│     • Missing                                                               │
│                                                                             │
│ • Playbook Engine                                                           │
│   - Suggests historical remediation                                         │
│   - Never auto-executes                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXPLAINABLE AI LAYER                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ LLM Responsibilities                                                        │
│                                                                             │
│ • Incident Summary                                                          │
│ • Root Cause Explanation                                                    │
│ • Investigation Steps                                                       │
│ • Remediation Guidance                                                      │
│                                                                             │
│ Rules                                                                       │
│ -----                                                                       │
│ • Every claim must cite an evidence_id                                      │
│ • Unsupported claims are regenerated                                        │
│ • LLM NEVER computes the root cause                                         │
│ • LLM only narrates structured analysis results                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Dashboard                                                                 │
│ • Live Topology                                                             │
│ • Timeline                                                                  │
│ • Ranked Root Causes                                                        │
│ • Evidence Explorer                                                         │
│ • Blast Radius Visualization                                                │
│ • Suggested Remediation                                                     │
│ • Audit Trail                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        HUMAN-IN-THE-LOOP                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ Operators can:                                                              │
│                                                                             │
│ • Confirm hypothesis                                                        │
│ • Reject hypothesis                                                         │
│ • Modify evidence weighting                                                 │
│ • Request additional evidence                                               │
│ • Approve simulated remediation only                                        │
│                                                                             │
│ Nothing executes automatically below confidence thresholds.                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     INCIDENT MEMORY & LEARNING                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ • Final Human-Confirmed Root Cause                                          │
│ • Resolution Applied                                                        │
│ • Reviewer Feedback                                                         │
│ • Similar Incident Retrieval                                                │
│ • Historical Co-occurrence Updates                                          │
│ • Permanent Audit History                                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

