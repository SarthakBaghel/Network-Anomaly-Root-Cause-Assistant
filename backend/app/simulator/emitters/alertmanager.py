from datetime import datetime

from app.simulator.emitters.base import BaseEmitter, iso_utc


class AlertmanagerEmitter(BaseEmitter):
    source_name = "simulator.alertmanager"

    def emit(self, *, fingerprint: str, starts_at: datetime, status: str, labels: dict, annotations: dict, scenario_id: str) -> dict:
        payload = {"fingerprint": fingerprint, "startsAt": iso_utc(starts_at), "status": status, "labels": labels, "annotations": annotations}
        return self.envelope(payload, scenario_id, starts_at)
