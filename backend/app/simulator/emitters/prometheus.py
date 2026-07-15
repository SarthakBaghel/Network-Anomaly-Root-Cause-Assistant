from datetime import datetime

from app.simulator.emitters.base import BaseEmitter, iso_utc


class PrometheusEmitter(BaseEmitter):
    source_name = "simulator.prometheus"

    def emit(
        self,
        *,
        sample_id: str,
        observed_at: datetime,
        metric: str,
        value: float,
        unit: str,
        labels: dict,
        scenario_id: str,
        provenance: dict | None = None,
    ) -> dict:
        payload = {
            "sample_id": sample_id,
            "observed_at": iso_utc(observed_at),
            "metric": metric,
            "value": value,
            "unit": unit,
            "labels": labels,
        }
        return self.envelope(payload, scenario_id, observed_at, provenance)
