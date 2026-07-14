# Dataset Integration Handoff — Network Anomaly RCA Prototype

**Purpose:** Give another development task enough authoritative context to use the expanded Drive dataset without violating the prototype architecture.  
**Governing source:** `NETWORK_ANOMALY_RCA_PROTOTYPE_BLUEPRINT.md` v1.5, especially §§3.3, 9.1, 10.3, 10.5, 22.3, and 25.  
**Detailed inventory supplied by user:** `/Users/sarthakbaghel/Downloads/DatasetDescription.md`.  
**Drive folder:** [Challenge 2 reference dataset](https://drive.google.com/drive/folders/130a9nKAY9X6rZsksXQ2RCqSakYrB4azB). Public read access and the visible inventory were verified on 2026-07-14. Keep this URL in documentation/local manifests only; runtime code, CI, and secrets must not depend on it.

---

## 1. Project context

The product is a **Network Anomaly Root-Cause Assistant**. It must ingest telemetry, logs, alerts, topology, and configuration changes; detect anomalies across time windows; correlate signals using identity/topology/trace/symptom evidence; rank probable causes; separate observed/correlated/conflicting/missing evidence; show a timeline; recommend safe next steps; and maintain an audit trail.

The P0 demo is one deterministic incident: disabling API-gateway rate limiting while raw ingress remains stable. Forwarded traffic and downstream pressure rise, a payment timeout appears, alerts fire, and RCA ranks a gateway configuration regression above DoS and database exhaustion. A nearby unrelated auth warning must be excluded. The top frozen score is `92.1`.

The reference datasets do **not** contain one naturally correlated version of this incident. They contribute realism; the deterministic scenario supplies cross-modal causal truth.

---

## 2. Expanded dataset inventory

| Dataset | Approximate content | Approved prototype use | Never assume |
|---|---|---|---|
| NSL-KDD | 41 network features plus class/difficulty metadata; legacy attacks | Feature vocabulary, normal-range exploration, attack terminology | It is timestamped service telemetry or contains gateway/config/log causality |
| UNSW-NB15 | Modern flow/connection features and attack labels | Connection/load/loss distribution study, network vocabulary | `label`/`attack_cat` may drive runtime detection or hypotheses |
| Loghub HDFS | ~11M historical distributed-system log lines | Parse grammar and a small attributed application-log template catalogue | HDFS hosts/timestamps belong to the prototype topology |
| Loghub BGL | ~4.7M HPC/kernel/RAS lines | Severity/fault vocabulary and small attributed system-log template catalogue | Node IDs or minute buckets are service/trace identity |
| GAIA MicroSS | Microservice description, anomaly-injection records, split metric/trace/business archives | Topology/injection schema reference and provenance | GAIA service IDs silently replace frozen entities or form the golden timeline |
| Sample trace dataset | Small train/val/test traces plus service/operation/status/latency dictionaries | Trace composition, status mapping, and latency-reference study | It requires no transformation or its labels may enter runtime |

Raw data is reference-only, outside the app repository, bootstrap, CI, runtime, and demo. Large raw files and extracted GAIA archives must not be committed.

### 2.1 Drive inventory verification

The public Drive UI confirms the following visible artifacts:

| Folder | Verified visible content |
|---|---|
| Root | `GAIA-DataSet-main/`, `loghub/`, `nsl_kdd/`, `sample_dataset/`, `unsw_nb15/`, and `DatasetDescription.md` (29 KB) |
| `loghub/HDFS/` | `HDFS.log` — Drive displays 1.47 GB |
| `loghub/BGL/` | `BGL.log` — Drive displays 708.8 MB |
| `nsl_kdd/` | ARFF/TXT train, 20% train, test, and Test-21 variants; nested `nsl-kdd/`; largest visible files are `KDDTrain+.arff` 17.9 MB and `.txt` 18.2 MB |
| `unsw_nb15/` | `UNSW_NB15_training-set.parquet` 9.2 MB and `UNSW_NB15_testing-set.parquet` 4.3 MB |
| `sample_dataset/` | `train.csv` 2 KB, `val.csv` 2 KB, `test.csv` 6 KB, and `id_manager/` |
| `sample_dataset/id_manager/` | `latency_range.yml` 32 KB, `operation_id.yml` 19 KB, `service_id.yml` 3 KB, `status_id.yml` 269 bytes |
| `GAIA-DataSet-main/GAIA-DataSet-main/` | `MicroSS/`, `README.md`, `LICENSE`, `.gitattributes`, `.gitignore` |
| `GAIA.../MicroSS/` | `business/`, `metric/`, `run/`, `trace/`, and `MicroSS system description.docx` 253 KB |

Drive reports folder sizes as unavailable, so the claimed GAIA aggregate size and split-archive completeness are not verified by this read-only inventory. The HDFS/BGL differences between rounded description sizes and Drive (`1.5 GB` vs `1.47 GB`; `743 MB` vs `708.8 MB`) are consistent with decimal/binary display differences but must be resolved through downloaded byte counts and SHA-256 manifests.

This verification proves names, presence, visible types, and displayed sizes only. It does **not** prove row counts, schemas, file integrity, decompression success, licenses, or that the contents match upstream releases. Those claims require the local manifest checks in §8.

---

## 3. Frozen data architecture

```text
Untouched reference datasets
  -> offline inspection/conversion only
  -> network_profile.json + log_templates.yaml + explicit mapping proposals
  -> deterministic scenario builder (seed 20260714)
  -> raw metrics.jsonl / logs.jsonl / alerts.jsonl / config_changes.jsonl
  -> four distinct source adapters + topology fixture loader
  -> CanonicalEvent pipeline
  -> detection -> incident -> topology/RCA -> evidence -> explanation/review/audit
```

The live demo replays raw scenario inputs through adapters. It may not insert canonical events or analysis outputs directly. Runtime feature packages may not read `expected/`, `ground_truth.json`, or `backend/tests/fixtures/golden_*`.

Frozen entities:

```text
api-gateway-01
checkout-api-01
payment-api-01
payment-db-01
auth-api-01
```

Frozen scenario and trace IDs:

```text
scenario_id: gateway_rate_limit_disabled
trace_or_session_id: scenario_gateway_rate_limit_001
```

---

## 4. Required output artifacts

Reference-data work may propose or regenerate only these bounded artifacts through reviewed code:

```text
backend/app/fixtures/reference_profiles/network_profile.json
backend/app/fixtures/reference_profiles/log_templates.yaml
backend/app/fixtures/detector_rules.yaml
backend/app/fixtures/scenarios/gateway_rate_limit/inputs/metrics.jsonl
backend/app/fixtures/scenarios/gateway_rate_limit/inputs/logs.jsonl
backend/app/fixtures/scenarios/gateway_rate_limit/inputs/alerts.jsonl
backend/app/fixtures/scenarios/gateway_rate_limit/inputs/config_changes.jsonl
backend/app/fixtures/scenarios/gateway_rate_limit/provenance.json
```

Test-only expectations remain below `expected/` or in `backend/tests/fixtures/`.

Every `REFERENCE_DERIVED` provenance entry requires dataset/file or record identity, retrieval date, license reference, source SHA-256, transformation version, declared synthetic fields, seed, explicit entity mapping where relevant, and derived-output SHA-256. Purely project-authored `SIMULATED` entries may retain the existing scenario manifest fields and output SHA-256 values.

Quality flags:

- `SIMULATED`: generated without reference influence.
- `REFERENCE_DERIVED`: values, ranges, names, or templates were informed by reference material.

Provenance is displayed for honesty but is not an RCA factor.

---

## 5. Corrections to apply before implementing DatasetDescription.md

The description is a useful inventory, not a transformation contract. Apply these corrections:

1. **No target leakage.** `class`, `label`, `attack_cat`, `difficulty_level`, GAIA injection labels, and sample trace anomaly labels may only select offline subsets or evaluate outputs. They may not determine runtime severity, alerts, hypothesis type/rank, anomaly score, incident membership, or signal values.
2. **Do not derive configuration hypotheses from attack labels.** UNSW `Exploits`/`Backdoors` do not mean `configuration_regression`. That candidate requires a real config-audit record and compatible later symptoms.
3. **Treat proposed network formulas as proxies.** NSL `count/duration`, byte/packet estimates, and UNSW `sinpkt * 15` are not measured RPS or p95 latency. Either name exploratory results with `_proxy` or omit them from P0. Use checked-in hand-reviewed scenario values and the sample latency ranges instead.
4. **Use correct signal semantics.** `wrong_fragment + urgent` is not TCP resets. UNSW `sloss` is loss/retransmission, not resets. Synthetic TCP-reset metrics must be clearly declared synthetic.
5. **Never manufacture traces from time.** The suggested BGL minute-bucket `trace_id` is forbidden. Use real trace/block/request IDs or the deterministic scenario trace. Time proximity alone must never create identity.
6. **No implicit closest-entity mapping.** HDFS/BGL components/nodes require an explicit versioned source-to-entity mapping; otherwise use them only to extract templates.
7. **Keep topology IDs frozen.** GAIA may inform edge patterns and injection-record shape, but changing the five entity IDs requires a reviewed blueprint/fixture/API change.
8. **Transform the sample trace dataset explicitly.** Combine high/low trace parts deterministically, decode service/operation/status dictionaries, declare source timezone, normalize to UTC, and provenance-tag the mappings. “No synthetic columns required” is not sufficient.
9. **Do not copy large/raw data.** Commit only small redistributable derived profiles/templates/fixtures where licensing permits.
10. **Do not auto-generate catalogues.** Dataset vocabulary can propose detector/hypothesis entries, but Persons 3 and 4 must review operational and causal meaning.

Also note that the NSL-KDD description heading says “41 columns” while listing 41 features plus class and difficulty metadata. Treat this as 41 input features and two metadata/label columns.

---

## 6. Ownership and review

| Area | Accountable | Review |
|---|---|---|
| Dataset manifest, provenance, converter, network/log profile content, scenario raw inputs, detector rules | Person 3 | Person 1 for schemas/CI; Person 4 for RCA semantics |
| Topology IDs/edges, symptom and hypothesis catalogue semantics | Person 4 | Person 1 schema validation; Person 3 source mapping |
| Loader/contract/migration/CI infrastructure | Person 1 | Content owner |
| UI provenance labels and raw-record display | Person 2 | Person 3 |
| Evidence wording and explanations | Person 5 | Persons 3 and 4 |

Do not follow the DatasetDescription artifact map where it conflicts with this ownership table.

---

## 7. Golden scenario constraints

- At least 20 baseline metric samples per scored signal.
- T+0: `rate_limit.enabled true -> false` on `api-gateway-01`.
- Raw ingress/source distribution remains stable.
- T+30: forwarded RPS/connections/utilization rise.
- T+40: TCP reset/retransmission scenario metrics rise.
- T+45: gateway alert.
- T+60: checkout p95 latency rises.
- T+75: payment upstream/connection timeout log.
- T+90: checkout error-rate alert.
- T+100: DB utilization remains normal, conflicting with DB exhaustion.
- T+120: unrelated auth certificate warning under `maintenance_auth_001`; it must be excluded.
- Expected candidates: configuration regression `92.1`, DoS/traffic surge `65.6`, DB exhaustion `41.5`.

Reference datasets may tune wording/ranges but must not change these frozen P0 outputs without the contract-change process.

---

## 8. Acceptance checklist for dataset integration

- [ ] Drive URL is documented; the machine-specific local root is provided through an ignored manifest; neither is a runtime dependency.
- [ ] Input file sizes and SHA-256 values match the manifest.
- [ ] License/usage references and retrieval dates are present.
- [ ] Raw files remain unchanged and outside Git.
- [ ] No forbidden label reaches runtime fixtures/profile/catalogues.
- [ ] Every synthetic/proxy field is named and declared.
- [ ] Every source identity mapping is explicit and versioned.
- [ ] Same input hashes + version + seed produce byte-identical outputs.
- [ ] Scenario raw files replay through all source adapters.
- [ ] Runtime import/open guard blocks expected/ground-truth/golden files.
- [ ] Reset/replay preserves event order, attachments, factor inputs, scores, and ranks.
- [ ] UI labels data as simulated or reference-derived, never live production telemetry.

---

## 9. Instruction to give the other Codex task

Use this exact instruction with the other task:

> Read `docs/dataset-thread-handoff.md`, `DatasetDescription.md`, blueprint v1.5 §§3.3, 9.1, 10.3, 10.5, 22.3, and decision M0-009 before touching dataset code. Treat the raw datasets as reference-only. Preserve the frozen simulator scenario, IDs, topology, adapters, provenance schema, ground-truth firewall, and ownership boundaries. Do not implement label-derived severity/hypotheses, time-bucket trace IDs, implicit entity mapping, or unlabelled metric proxies. First report which bounded artifact you will produce and its consumer test; then implement it without modifying unrelated owned files.
