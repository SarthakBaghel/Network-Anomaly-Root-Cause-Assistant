# Reference-Derived Scenario Extensions

**Status:** Implemented and release-gate verified on 2026-07-16  
**Relationship to the blueprint:** Additive, post-blueprint extension

## Why this document exists

The original [`BLUEPRINT.md`](../BLUEPRINT.md) defines the primary gateway
rate-limit regression and its fixed Milestone-0 contracts. It does not require
the six reference-derived scenarios, trace ingestion, or the HDFS topology.
Those capabilities were added later to demonstrate that the prototype can
apply the same detection-to-RCA workflow across several network and distributed
system failure classes.

This document records that additional scope without rewriting the original
blueprint. The primary golden scenario remains supported and deterministic.

## What deterministic means here

Deterministic does not mean that the UI returns one hardcoded answer. Events
still pass through normalisation, validation, detectors, incident correlation,
topology analysis, hypothesis scoring, evidence matching, recommendation
selection, and explanation generation.

It means that the simulator uses fixed inputs, a fixed seed, versioned
catalogues, and stable ordering. Replaying the same scenario against the same
versions must therefore produce the same semantic result. Database IDs and
wall-clock timestamps may differ, but the detected incident, ranked evidence,
RCA result, topology state, recommendations, and audit ordering must not.

## Implemented scenario catalogue

| Scenario ID | Display name | Reference data | Primary observed signals | Expected top RCA type |
|---|---|---|---|---|
| `network_path_congestion` | Network-path degradation | GAIA MicroSS, UNSW-NB15 | Packet loss, TCP retransmissions, path latency | `network_path_congestion` |
| `ddos_syn_flood` | DDoS / SYN flood | UNSW-NB15, NSL-KDD | Ingress surge, SYN failures, source-distribution shift | `dos_or_traffic_surge` |
| `gaia_resource_saturation` | GAIA resource saturation | GAIA MicroSS | CPU saturation, memory saturation, service latency | `resource_saturation` |
| `port_scan_reconnaissance` | Port scan / reconnaissance | UNSW-NB15, NSL-KDD | Port fan-out, rejected connections, destination fan-out | `external_probe` |
| `hdfs_datanode_failure` | HDFS DataNode failure | Loghub HDFS | DataNode failure, I/O errors, replica degradation | `distributed_storage_node_failure` |
| `trace_anomaly` | Distributed trace anomaly | Sample traces | Critical-path latency, span error, missing parent span | `trace_latency_regression` |

The simulator also includes non-reference-derived database pool, DNS, and TLS
failure scenarios. They share the same production pipeline but are outside the
dataset-extension scope recorded here.

## How local datasets are connected

The multi-gigabyte source datasets are development references, not live
production dependencies. They remain in the git-ignored `/data/` directory.
The application does not load them whenever a presenter clicks **Trigger
scenario**.

Instead, versioned deterministic transforms extract useful signal shapes and
vocabulary into small curated telemetry profiles. The current transform is
`reference-scenario-builder-1.0`. Every derived runtime event records:

- reference dataset names;
- the curated profile identifier;
- retrieval date and licence reference;
- transformation version and seed;
- fields created by simulation; and
- the `REFERENCE_DERIVED` quality marker.

This design keeps the live demo fast, offline-capable, reproducible, and honest
about which values were synthesised.

## Pipeline and contract extensions

The scenarios use the same production ingestion and investigation path as the
golden scenario. The post-blueprint additions are:

- a first-class `trace` modality and `simulator.trace` source;
- network-path, DDoS, resource, reconnaissance, HDFS, and trace signal
  families;
- matching detector and hypothesis catalogue entries;
- exact hypothesis-declared diagnostic and remediation playbook IDs;
- HDFS client, NameNode, and DataNode entities in topology version
  `topology-1.2`; and
- scenario provenance fields in the API and generated frontend contract.

The versioned catalogues are `detector-rules-1.2`,
`symptom-families-1.2`, `hypotheses-1.5`, and `playbooks-1.4`.
Recommendations remain suggestions only; every catalogue playbook requires
human approval and the prototype never executes remediation automatically.

### Three evidence-backed contenders per scenario

Every demonstration scenario publishes exactly three conditional, catalogue-
backed contenders. They are not duplicate placeholders and are not selected by
reading the scenario ID. Observed anomaly and log types open the candidate
gates; topology, symptom compatibility, propagation, metrics, direct records,
change causality, time, and history then produce the deterministic evidence
score. Missing evidence remains visible and lowers the weaker alternatives.

| Scenario | Ranked contender types |
|---|---|
| Gateway rate-limit disabled | `configuration_regression`, `dos_or_traffic_surge`, `database_connection_exhaustion` |
| Network-path degradation | `network_path_congestion`, `upstream_service_failure`, `resource_saturation` |
| DDoS / SYN flood | `dos_or_traffic_surge`, `gateway_capacity_saturation`, `external_probe` |
| GAIA resource saturation | `resource_saturation`, `upstream_service_failure`, `network_path_congestion` |
| Port scan / reconnaissance | `external_probe`, `authorized_security_scanner`, `dos_or_traffic_surge` |
| HDFS DataNode failure | `distributed_storage_node_failure`, `storage_network_partition`, `namenode_metadata_failure` |
| Distributed trace anomaly | `trace_latency_regression`, `upstream_service_failure`, `network_path_congestion` |
| Database pool exhaustion | `database_connection_exhaustion`, `database_query_regression`, `database_resource_saturation` |
| DNS resolution failure | `dns_resolution_failure`, `upstream_service_failure`, `network_path_congestion` |
| TLS certificate failure | `certificate_or_tls_failure`, `upstream_service_failure`, `network_path_congestion` |

The investigation UI labels the score as **evidence confidence** and shows a
Strong, Moderate, or Limited tier plus the numeric score out of 100. This is a
transparent evidence score, not a statistical probability of correctness.

For reconnaissance, an explicit allow-list match and approved scan ticket can
raise `authorized_security_scanner` above `external_probe`; that same record is
also conflicting evidence against an external probe. Adversarial tests verify
that these reconnaissance-specific contenders do not leak into unrelated
incidents.

## Data-leakage boundary

Dataset outcome columns such as attack class, class label, difficulty, and
trace anomaly labels are useful for offline validation but are forbidden from
runtime ingestion. The recursive ingress firewall rejects these fields even
when they are nested. Offline readers may retain them only under `_meta`, and
the pipeline runner strips `_meta` before building canonical events.

Consequently, runtime RCA is based on observed telemetry rather than copying a
dataset answer into the incident or hypothesis.

## Simulator lifecycle

The **Start** button runs a finite healthy-baseline replay. It automatically
changes from `running` to `ready` after all baseline ticks have been emitted.
That automatic transition is intentional: `ready` means the baseline is
complete and a scenario can be triggered. **Stop** is only needed to interrupt
the baseline before completion. Use **Reset** before starting a new run.

After **Trigger scenario**, the curated incident replay completes
synchronously and the state becomes `completed`. This bounded lifecycle avoids
background event drift during a deterministic demonstration.

## Recommended demonstration flow

1. Click **Reset** to clear prior demo data and restore the fixture topology.
2. Click **Start** and wait for the state to become `ready`.
3. Choose one of the six scenarios and show its reference datasets,
   transformation version, expected signals, and difficulty.
4. Click **Trigger scenario** and watch source health, accepted events,
   anomalies, and the incident list update.
5. Open the incident and explain the timeline, topology impact path, ranked
   hypotheses, supporting/conflicting/missing evidence, and safe catalogue
   recommendations.
6. Optionally enable Ollama for a natural-language summary. Ollama can narrate
   only the validated evidence bundle; it cannot change ranks, scores,
   evidence, or recommendations.

For the strongest contrast, demonstrate the original configuration regression
first and then DDoS / SYN flood: similar gateway symptoms lead to different RCA
because one contains a configuration change while the other contains an
external ingress and source-distribution surge.

## Run and verification commands

First-time setup and the combined development command:

```bash
cp .env.example .env
./scripts/bootstrap.sh
./scripts/dev.sh
```

Verify all production, backend, frontend, generated-contract, security, and
live-browser boundaries twice:

```bash
make verify
```

Validate the local raw-dataset bridges separately:

```bash
.venv/bin/python scripts/validate_dataset_pipeline.py
```

Raw dataset validation can report warnings for noisy or incomplete source
slices. The release scenarios themselves are covered by production integration
tests that assert the expected top RCA type and zero quarantined records.

## Verification record

The latest 2026-07-16 release gate completed two full passes, including production
artifact reproduction, backend tests, frontend tests and build, generated API
contract checks, secret and runtime-firewall checks, and MSW-disabled live
Playwright. Both passes produced the same semantic snapshot digest:

`sha256:9a404aa2a00ad103bf4a421c3b54ff5421fe45c154fa84ee1d0c30c01a3651aa`
