# Prototype Demo Script & Talking Points

This script is the step-by-step guide for performing a 4–6 minute live demonstration of the **Network Anomaly Root-Cause Assistant** prototype. 

---

## ⏱️ Demo Timeline Overview

| Section | Topic | Duration |
|---|---|---|
| **1** | Introduction & Baseline | 0:00 – 1:00 |
| **2** | Scenario Trigger & Anomaly Ingestion | 1:00 – 2:00 |
| **3** | Incident Investigation (Timeline & Topology) | 2:00 – 3:30 |
| **4** | Hypotheses & Evidence Explorer | 3:30 – 4:45 |
| **5** | Human Review & Audit Trail | 4:45 – 5:30 |
| **6** | Fallbacks & Hardening | 5:30 – 6:00 |

---

## 🎤 Section-by-Section Script & UI Steps

### Section 1 — Introduction & Baseline (0:00 – 1:00)

**UI Actions:**
1. Open the browser to the main dashboard `/`.
2. Point out the **Source Health Bar** at the top.
3. Hover over the five adapter health cards.

**Talking Points:**
* "Welcome to the demo of our Network Anomaly Root-Cause Assistant."
* "The system starts in a healthy baseline state. At the top of our Operations Overview, we see the live health and event counters for our **five distinct telemetry adapters**: Metrics from Prometheus, Application Logs from Syslog, Alerts from Alertmanager, Configuration Changes from our deployment audit feed, and our CMDB Topology load status."
* "Our data strategy is **strictly honest**: these adapters normalise multiple raw stream formats into a single `CanonicalEvent` schema. Public datasets like NSL-KDD, UNSW-NB15, and LogHub informed our log format and anomaly profiles, but they are not required at runtime. The live system runs entirely from our deterministic telemetry simulator."
* "At this moment, the network topology is clean, the baseline metric rate is stable at **7,800 requests per second** (RPS), and no incidents are open."

---

### Section 2 — Scenario Trigger & Anomaly Ingestion (1:00 – 2:00)

**UI Actions:**
1. Select scenario `gateway_rate_limit_disabled` (ID: `scenario_gateway_rate_limit_001`) from the dropdown.
2. Click the **Trigger Scenario** button (identifiable by `scenario-trigger-btn` test ID).
3. Point to the **Recent Anomalies Table** and the **Incident List** as they populate on the poll interval.

**Talking Points:**
* "We will now trigger our primary golden scenario: `disabled_gateway_rate_limiting`."
* "At T+0, a deployment bot disables the rate limiter on `api-gateway-01` to troubleshoot a checkout issue. The config audit adapter immediately ingests this change."
* "Because the rate limiter is disabled, forwarded traffic spikes from our baseline of 2,400 to the full client request load of **7,800 RPS**."
* "This sudden spike cascades down the stack. We see metric anomalies for TCP resets and TCP retransmissions rising on `api-gateway-01`."
* "Within 45 seconds, Alertmanager fires a `HighForwardedRequestRate` critical alert. Shortly after, the checkout API latency spikes, database connections saturate, and upstream connection timeouts start appearing on `payment-api-01`."
* "As these anomalies enter, our rolling Z-score detectors and template rules evaluate them. The incident manager correlates them and automatically opens Incident **`inc_001`**: *Checkout degradation through API gateway*."

---

### Section 3 — Incident Investigation: Timeline & Topology (2:00 – 3:30)

**UI Actions:**
1. Click on the open incident in the table to navigate to `/incidents/inc_001`.
2. Point out the **Timeline Panel** and hover over dots in the Metric, Log, Alert, and Config lanes.
3. Point out the **Topology Impact Graph** showing the traversed path.

**Talking Points:**
* "Let’s investigate the incident. The page displays a single consistent snapshot under analysis run `run_007`. We never mix data from different runs."
* "Our **Incident Timeline** maps our canonical events across four lanes. Notice that our configuration change at T+0 is successfully attached because it falls within our lookback window and directly targets `api-gateway-01`. Our timeline visually separates attached events from excluded events like the Certificate Expiry warning on `auth-api-01`, which is muted because it is topologically isolated and belongs to an unrelated symptom family."
* "In our **Topology Impact Graph**, we see our system services arranged by relationships. Suspected root cause node `api-gateway-01` is highlighted in red, primary affected checkout nodes in amber, and the propagation path is traced down to the database."
* "Our layout highlights the `sends_traffic_to` propagation path to show where the traffic flowed. A legend clearly distinguishes this from the structural `depends_on` traversal rules used by the algorithm, preventing the operator from confusing traffic direction with service dependency."

---

### Section 4 — Hypotheses & Evidence Explorer (3:30 – 4:45)

**UI Actions:**
1. Scroll down to the **Ranked Hypotheses** list.
2. Expand the top hypothesis (`api-gateway-01` configuration regression) to show the factor scores.
3. Point out the **Evidence Explorer** and expand its four sections: Observed facts, Correlated signals, Conflicting evidence, and Missing evidence.

**Talking Points:**
* "The system ranks three probable root causes. At Rank 1 is our `configuration_regression` hypothesis targeting `api-gateway-01`, with an **Evidence score** of exactly **`92.1`**."
* "Every factor contributing to this score is transparently displayed: symptom compatibility, propagation consistency, change causal fit, temporal proximity, and a historical similarity of 0.5 derived from our one seeded historical rate-limit incident."
* "Our **Evidence Explorer** categorises all facts to reduce operator confirmation bias:
  1. **Verified observed facts**: We explicitly label these to confirm that metrics and logs were observed without claiming they prove causation.
  2. **Correlated signals**: Logs showing timeouts down the stack.
  3. **Conflicting evidence**: This is a key differentiator. The raw client ingress rate remained stable before and after the trigger, weakening the external DoS hypothesis. Additionally, database utilization metrics remained normal, contradicting the database exhaustion hypothesis.
  4. **Missing evidence**: Things the detector expected but did not find—such as WAF decision logs or network firewall blocks. These are surfaced as concrete collection requests."

---

### Section 5 — Human Review & Audit Trail (4:45 – 5:30)

**UI Actions:**
1. Point out the **Catalogue recommendation** (labelled *“Catalogue recommendation — not executed”*).
2. Click the **Confirm** button on the Rank 1 hypothesis.
3. Scroll to the **Audit Trail** panel at the bottom to show the `REVIEW_CONFIRMED` audit entry.

**Talking Points:**
* "Below our evidence, we display safe diagnostic playbooks from our catalogue. These are suggestion-only and clearly marked as unexecuted to ensure human control."
* "To resolve the incident, the operator clicks **Confirm**. The UI sends this review action with a unique `client_action_id` to prevent duplicate submissions."
* "Once confirmed, the hypothesis status changes to **'Confirmed root cause'**—which is the only place this causal wording is permitted. The incident status updates to `resolved`."
* "Every action is captured in our append-only **Audit Trail** below. We see the `REVIEW_CONFIRMED` audit log entry with the actor, timestamp, and revision details. This table is strictly read-only to ensure forensic durability."

---

### Section 6 — Fallbacks & Hardening (5:30 – 6:00)

**UI Actions:**
1. Scroll back up and click the **Reset Simulator** button (`simulator-reset-btn`) on the dashboard overview or configuration panel to show the dashboard return to healthy baseline.

**Talking Points:**
* "Finally, we demonstrate the prototype's self-healing reset capability. Clicking **Reset** executes our synchronous purge: stopping the simulator emitters, clearing demo database rows, reloading our CMDB topology from the read-only fixture, re-seeding our historical database, and logging a `DEMO_RESET` audit entry."
* "If our live simulator ever fails on stage, our primary fallback is a deterministic replay of our scenario inputs. If our API fails, our catastrophic UI fallback displays a read-only cached investigation snapshot. The app is fully hardened to run offline under any network conditions."
* "This concludes our walk-through of the Network Anomaly Root-Cause Assistant."

---

## 🚨 Demo Fallback Procedures

In case of live failures during presentation, follow these instructions:

### Failure Scenario A: Live Telemetry Generation Fails
1. **Symptom:** Emitters do not update or frontend health cards display `error`.
2. **Action:** Click the **Reset** button to force a clean DB wipe.
3. **If Reset fails:** Run the seed script manually from the terminal:
   ```bash
   python scripts/seed_demo.py
   ```
4. **Offline Replay:** Trigger scenario replay manually using:
   ```bash
   python scripts/verify_demo.py
   ```
   This loads the pre-packaged canonical event stream directly into the database, bypassing simulator network routes.

### Failure Scenario B: UI Graph fails to Render
1. **Symptom:** `@xyflow/react` shows a blank node space or throws layout errors.
2. **Action:** Reload the page with `Ctrl+F5` to clear cache.
3. **Reasoning:** Ensure `topology.json` contains exactly the five frozen entity IDs. If a custom edge was added, verify it has a valid relation type (`depends_on` or `sends_traffic_to`).

### Failure Scenario C: Port Contention on Startup
1. **Symptom:** Backend or frontend refuses to bind to port `8000` or `5173`.
2. **Action:** Kill any running uvicorn/node processes:
   ```powershell
   Get-Process -Name python, node | Stop-Process -Force
   ```
   Then re-run the bootstrapper:
   ```bash
   ./scripts/bootstrap.sh
   ```
