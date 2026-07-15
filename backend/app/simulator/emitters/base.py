from datetime import datetime, timezone
from typing import Any

from app.config import settings


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class BaseEmitter:
    source_name: str

    def envelope(
        self,
        payload: dict[str, Any],
        scenario_id: str,
        emitted_at: datetime,
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "scenario_id": scenario_id,
            "emitted_at": iso_utc(emitted_at),
            "provenance": provenance
            or {
                "profile": "network_profile-1.0",
                "seed": settings.simulator_seed,
                "derivation_version": "1.0",
            },
            "payload": payload,
        }

    def replay(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Re-emit a checked-in source record without changing its provenance."""
        emitted_at = datetime.fromisoformat(raw["emitted_at"].replace("Z", "+00:00"))
        return self.envelope(raw["payload"], raw["scenario_id"], emitted_at, raw["provenance"])
