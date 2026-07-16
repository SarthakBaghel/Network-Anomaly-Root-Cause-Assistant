# Network Anomaly Root-Cause Assistant

## Project overview

The Network Anomaly Root-Cause Assistant is an explainable network-operations
prototype that converts mixed operational telemetry into ranked, evidence-backed
root-cause hypotheses.

Modern incidents rarely appear in one monitoring system. A gateway problem can
surface as elevated connection counts, application timeouts, alerts,
configuration changes, and downstream service degradation. Looking at those
signals independently creates alert noise; correlating them only by timestamp
can blame an unrelated event.

This project combines metrics, logs, alerts, configuration changes, distributed
traces, and dependency topology in one deterministic investigation workflow. It
shows what happened, which entities were affected, why one explanation ranks
above competing alternatives, what evidence is missing or conflicting, and
which safe next steps an operator can consider.

## What the prototype demonstrates

- Multimodal ingestion through Prometheus-style metrics, syslog/application
  logs, Alertmanager events, configuration audit records, traces, and a CMDB
  topology fixture.
- Statistical, rule-based, trace, and topology-cascade anomaly detection.
- Entity-scoped incident correlation that avoids treating every nearby event as
  relevant.
- Directed dependency and traffic-path analysis for impact and blast radius.
- Ranked root-cause hypotheses with transparent factor scores.
- Separate observed, correlated, conflicting, and missing evidence.
- Catalogue-backed diagnostic and remediation suggestions requiring human
  approval.
- Immutable analysis snapshots, human review, and an append-only audit trail.
- Downloadable Markdown and ReportLab PDF shift-handover reports.
- Optional local Ollama narration and a stateless Network Concepts Assistant.

## Demonstration scenarios

The original gateway configuration-regression scenario is accompanied by
network-path degradation, DDoS/SYN flood, resource saturation, port-scan
reconnaissance, HDFS DataNode failure, distributed trace anomaly, database
connection-pool exhaustion, DNS failure, and TLS certificate failure.

These scenarios are deterministic: replaying the same versioned fixture with
the same seed produces the same semantic investigation. Deterministic does not
mean the answer is hardcoded. Events still pass through validation, detection,
incident correlation, topology analysis, candidate generation, ranking,
evidence collection, recommendation selection, and explanation publication.

## Typical demonstration flow

1. Reset the environment.
2. Run the finite clean baseline until the simulator becomes ready.
3. Select and trigger a failure scenario.
4. Watch source health, anomalies, and the active incident update.
5. Open the incident to inspect its timeline and topology impact graph.
6. Compare ranked hypotheses and supporting, conflicting, and missing evidence.
7. Review safe next steps, record an operator decision, or export a handover
   report.

## Design principles

- **Evidence before narration:** deterministic analysis owns the facts; an LLM
  can describe validated results but cannot change them.
- **Causation is more than timing:** entity identity, topology, expected signal
  requirements, change causality, and conflicting evidence influence ranking.
- **Reproducible by default:** fixed seeds, versioned catalogues, generated
  contracts, and a two-pass release gate protect the demo from drift.
- **Safe recommendations:** playbooks are advisory and never execute
  remediation automatically.
- **Local-first operation:** SQLite and optional local Ollama keep the prototype
  self-contained.

## Start here

For architecture, technology choices, data flow, API boundaries, setup, and
verification commands, read the [technical README](./README.md).

For a presentation walkthrough, read the [demo script](./docs/demo-script.md).
The original requirements and frozen implementation contract remain available
in [BLUEPRINT.md](./BLUEPRINT.md), while additive features are recorded under
[`docs/`](./docs/).
