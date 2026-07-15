from datetime import datetime
from typing import Any

from app.simulator.emitters.base import BaseEmitter, iso_utc


class ConfigAuditEmitter(BaseEmitter):
    source_name = "simulator.config_audit"

    def emit(self, *, change_id: str, changed_at: datetime, target_entity_id: str, actor: str, config_key: str, old_value: Any, new_value: Any, change_ticket: str, scenario_id: str) -> dict:
        payload = {"change_id": change_id, "changed_at": iso_utc(changed_at), "target_entity_id": target_entity_id, "actor": actor, "config_key": config_key, "old_value": old_value, "new_value": new_value, "change_ticket": change_ticket}
        return self.envelope(payload, scenario_id, changed_at)
