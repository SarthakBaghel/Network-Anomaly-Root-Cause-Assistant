# Challenge 2: Network Anomaly Root-Cause Assistant
## Problem Statement: 
Build a Network Anomaly Root-Cause Assistant that ingests telemetry, logs, alerts, topology data, and configuration changes to detect anomalies and generate explainable root-cause hypotheses. The solution must distinguish correlation from likely causation, rank probable causes, and provide supporting evidence.

### What participants need to build:
1. Ingest telemetry, logs, alerts, topology data, and configuration change records from multiple sources.
2. Detect anomalies across relevant time windows.
3. Correlate metrics, logs, alerts, and configuration changes while avoiding simple time-based blame.
4. Use topology or dependency data to understand impact paths across network or system components.
5. Produce ranked root-cause hypotheses with supporting evidence.
6. Clearly separate confirmed evidence, correlated signals, and missing evidence.
7. Generate Incident Timeline what happened and when
8. Recommend next diagnostic or remediation steps and maintain an auditable trail
