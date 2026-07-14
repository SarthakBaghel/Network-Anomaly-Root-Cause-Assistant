from __future__ import annotations

import re
from typing import Any


SENSITIVE_KEY = re.compile(r"^(password|passwd|token|secret|api_key|authorization)$", re.IGNORECASE)
REDACTED = "[REDACTED]"


def redact_payload(value: Any) -> tuple[Any, bool]:
    changed = False

    def visit(item: Any) -> Any:
        nonlocal changed
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for key, child in item.items():
                if SENSITIVE_KEY.fullmatch(str(key)):
                    result[key] = REDACTED
                    changed = True
                else:
                    result[key] = visit(child)
            return result
        if isinstance(item, list):
            return [visit(child) for child in item]
        return item

    return visit(value), changed
