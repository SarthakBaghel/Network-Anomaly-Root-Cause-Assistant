"""Source-adapter implementations."""

from app.ingestion.adapters.alertmanager import AlertmanagerAdapter
from app.ingestion.adapters.config_audit import ConfigAuditAdapter
from app.ingestion.adapters.gaia_run import GaiaRunAdapter
from app.ingestion.adapters.prometheus import PrometheusAdapter
from app.ingestion.adapters.syslog import SyslogAdapter

ADAPTERS = {adapter.source_name: adapter for adapter in (
    PrometheusAdapter(), SyslogAdapter(), AlertmanagerAdapter(), ConfigAuditAdapter(),
    GaiaRunAdapter(),
)}

__all__ = [
    "ADAPTERS",
    "AlertmanagerAdapter", "ConfigAuditAdapter",
    "GaiaRunAdapter",
    "PrometheusAdapter", "SyslogAdapter",
]

