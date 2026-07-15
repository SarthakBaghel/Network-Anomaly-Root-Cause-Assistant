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
`symptom-families-1.2`, `hypotheses-1.3`, and `playbooks-1.2`.
Recommendations remain suggestions only; every catalogue playbook requires
human approval and the prototype never executes remediation automatically.

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

The 2026-07-16 release gate completed two full passes, including production
artifact reproduction, backend tests, frontend tests and build, generated API
contract checks, secret and runtime-firewall checks, and MSW-disabled live
Playwright. Both passes produced the same semantic snapshot digest:

`sha256:196ff3c123a4e9ca73a3aa7934f03696b2de7e38539de06295a23ea42fff9419`

