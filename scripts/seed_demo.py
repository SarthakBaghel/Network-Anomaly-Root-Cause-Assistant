from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import delete

from app.db.models import HistoricalIncident
from app.db.session import session_scope


def main() -> None:
    with session_scope() as session:
        session.execute(delete(HistoricalIncident))
        session.add(
            HistoricalIncident(
                id="hist_gateway_rate_limit_001",
                fingerprint="gateway-rate-limit-half-feature-match",
                confirmed_cause="configuration_regression",
                summary="Prior gateway incident confirmed after a rate-limit configuration regression.",
                feature_vector={
                    "entity_type": "gateway",
                    "change_type": "rate_limit.enabled",
                    "forwarded_traffic_spike": True,
                    "same_confirmed_cause": True,
                    "similarity": 0.5,
                },
            )
        )
    print("seeded deterministic historical incident (historical_similarity=0.5)")


if __name__ == "__main__":
    main()

