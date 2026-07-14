# Person 3 — Phase 0 and Phase 1

This backend combines Person 1's Milestone 0 foundation with Person 3's deterministic
Phase 1 simulator. Persistence, deduplication, quarantine, ingestion endpoints, and
runtime anomaly detection belong to later phases.

## Setup and verification (PowerShell)

From `backend`:

```powershell
python -m pip install -e ".[test]"
python -m pytest
```

Run the simulator API:

```powershell
python -m uvicorn app.main:app --reload
```

Routes:

- `POST /api/v1/simulator/start`
- `POST /api/v1/simulator/stop`
- `POST /api/v1/simulator/reset`
- `POST /api/v1/simulator/scenarios/gateway_rate_limit/trigger`
- `GET /api/v1/simulator/status`

`reset` resets simulator-owned clock, lifecycle, cursor, and counters only. Person 1's
cross-domain reset service remains responsible for clearing persistent application data.
