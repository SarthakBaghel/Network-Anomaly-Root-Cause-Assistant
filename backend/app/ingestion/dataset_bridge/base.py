"""
Dataset Bridge — base class for all dataset readers.

Every dataset reader produces an iterator of pre-formed raw dicts that
are ready to pass directly into IngestionPipeline.ingest(). Each dict
uses the EXACT same outer wrapper and payload schema that the simulator
emits (verified against the live adapters in test_dataset_bridge.py).

Outer wrapper schema (all datasets):
    {
        "scenario_id":   str,   ← "gateway_rate_limit_disabled" so SIMULATED flag is set
        "emitted_at":    str,   ← ISO-8601 UTC timestamp
        "provenance": {
            "origin":                 str,
            "origin_record_id":       str,
            "retrieved_at":           str,
            "license_reference":      str,
            "transformation_version": str,
            "synthetic_fields":       list[str],
            "seed":                   int,
        },
        "payload": { ... }    ← adapter-specific fields (see individual modules)
    }

Reference: DatasetDescription.md (all §1-§6 synthetic column derivation rules)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Canonical scenario_id keeps SIMULATED quality flag intact (pipeline.py: simulated_flags)
SCENARIO_ID = "gateway_rate_limit_disabled"

# Frozen base timestamp (P3 scenario anchor: 2026-07-14T09:00:00Z)
BASE_TIMESTAMP = datetime(2026, 7, 14, 9, 0, 0, tzinfo=timezone.utc)

# Seed from DatasetDescription.md §Provenance Tags
PROVENANCE_SEED = 20260714

# Frozen entity IDs from topology.json — the only valid entity_id values
ENTITY_IDS = {
    "api-gateway-01",
    "payment-api-01",
    "checkout-api-01",
    "auth-api-01",
    "payment-db-01",
}

DEFAULT_ENTITY_ID = "api-gateway-01"

# DatasetDescription.md §1 & §2: service-field value -> frozen entity_id
SERVICE_TO_ENTITY: dict[str, str] = {
    # NSL-KDD service column values
    "http":      "api-gateway-01",
    "ftp_data":  "api-gateway-01",
    "ftp":       "payment-api-01",
    "smtp":      "checkout-api-01",
    "ssh":       "auth-api-01",
    "domain_u":  "payment-db-01",
    "other":     "api-gateway-01",
    # UNSW-NB15 service column values
    "dns":       "api-gateway-01",
    "-":         "api-gateway-01",
    # protocol fallbacks
    "tcp":       "api-gateway-01",
    "udp":       "checkout-api-01",
}

# DatasetDescription.md §1 & §2: attack class -> blueprint hypothesis_type
HYPOTHESIS_MAP: dict[str, str] = {
    # NSL-KDD
    "neptune":          "dos_or_traffic_surge",
    "smurf":            "dos_or_traffic_surge",
    "back":             "dos_or_traffic_surge",
    "teardrop":         "dos_or_traffic_surge",
    "ipsweep":          "external_probe",
    "portsweep":        "external_probe",
    "satan":            "external_probe",
    "rootkit":          "configuration_regression",
    "buffer_overflow":  "configuration_regression",
    "loadmodule":       "configuration_regression",
    "warezclient":      "configuration_regression",
    "guess_passwd":     "configuration_regression",
    # UNSW-NB15
    "DoS":              "dos_or_traffic_surge",
    "Generic":          "dos_or_traffic_surge",
    "Fuzzers":          "dos_or_traffic_surge",
    "Exploits":         "configuration_regression",
    "Backdoors":        "configuration_regression",
    "Reconnaissance":   "external_probe",
    "Shellcode":        "configuration_regression",
    "Worms":            "dos_or_traffic_surge",
    "Analysis":         "external_probe",
}


def make_provenance(
    *,
    origin: str,
    origin_record_id: str,
    license_reference: str,
    synthetic_fields: list[str],
) -> dict[str, Any]:
    """Build a provenance dict matching the DatasetDescription.md §Provenance Tags spec."""
    return {
        "origin":                 origin,
        "origin_record_id":       origin_record_id,
        "retrieved_at":           "2026-07-14",
        "license_reference":      license_reference,
        "transformation_version": "dataset-bridge-1.0",
        "synthetic_fields":       synthetic_fields,
        "seed":                   PROVENANCE_SEED,
    }


def entity_from_service(service_value: str) -> str:
    """Map a raw service/protocol field value to a frozen entity_id."""
    return SERVICE_TO_ENTITY.get(str(service_value).strip(), DEFAULT_ENTITY_ID)


class DatasetReader(ABC):
    """
    Abstract base for all dataset readers.

    Subclasses implement ``records()`` which yields raw dicts ready for
    ``IngestionPipeline.ingest(source=..., raw=raw_dict, ...)``.
    """

    #: Source adapter key — must be a key in ``app.ingestion.adapters.ADAPTERS``
    source_name: str

    #: Maximum rows to yield (None = all rows). Override per reader or at call time.
    default_limit: int | None = None

    @abstractmethod
    def records(
        self,
        data_root: Path,
        *,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Yield raw dicts ready for IngestionPipeline.ingest().

        Args:
            data_root: Absolute path to the project ``data/`` directory.
            limit: Maximum rows to yield. Overrides ``default_limit``.
                   Pass None to use ``default_limit``; 0 means all rows.
        """

    def _effective_limit(self, limit: int | None) -> int | None:
        """Resolve limit from call argument vs class default."""
        if limit is not None:
            return limit if limit > 0 else None   # 0 -> unlimited
        return self.default_limit


__all__ = [
    "BASE_TIMESTAMP",
    "DEFAULT_ENTITY_ID",
    "ENTITY_IDS",
    "HYPOTHESIS_MAP",
    "PROVENANCE_SEED",
    "SCENARIO_ID",
    "SERVICE_TO_ENTITY",
    "DatasetReader",
    "entity_from_service",
    "make_provenance",
]
