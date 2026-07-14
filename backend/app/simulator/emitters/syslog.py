from datetime import datetime

from app.simulator.emitters.base import BaseEmitter, iso_utc


class SyslogEmitter(BaseEmitter):
    source_name = "simulator.syslog"

    def emit(self, *, record_id: str, timestamp: datetime, host: str, facility: str, level: str, code: str, message: str, trace_id: str, attributes: dict, scenario_id: str) -> dict:
        payload = {"record_id": record_id, "observed_at": iso_utc(timestamp), "host": host, "facility": facility, "level": level, "code": code, "message": message, "trace_id": trace_id, "attributes": attributes}
        return self.envelope(payload, scenario_id, timestamp)
