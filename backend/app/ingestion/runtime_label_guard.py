from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


# Dataset outcome fields are permitted in offline evaluation outputs, never in
# runtime events. Keeping the check at the ingestion boundary prevents target
# leakage even when a new adapter is introduced later.
FORBIDDEN_RUNTIME_LABEL_KEYS = frozenset(
    {
        "attack_cat",
        "label",
        "class",
        "difficulty_level",
        "nodeLatencyLabel",
        "graphLatencyLabel",
        "graphStructureLabel",
    }
)


def contains_forbidden_label(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key) in FORBIDDEN_RUNTIME_LABEL_KEYS or contains_forbidden_label(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_forbidden_label(item) for item in value)
    return False
