# Person 3 — Event pipeline, ingestion, and detection

Person 3's scope is implemented end to end: deterministic provenance fixtures,
the simulator and source emitters, normalization/quarantine/deduplication,
cursor-paginated ingestion APIs, and runtime anomaly detection.

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

`reset` delegates to Person 1's cross-domain reset service, which clears demo
data and then invokes Person 3's deterministic simulator-state reset hook.

Fixture regeneration is deterministic:

```powershell
python ../scripts/build_network_profile.py --check
```

`POST /api/v1/events/batch` preserves input order and defers orchestration until
all records are persisted. `GET /api/v1/events` returns `items` and an opaque,
filter-bound `next_cursor` ordered by `(timestamp DESC, event_id DESC)`.
